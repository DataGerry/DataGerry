/*
* DATAGERRY - OpenSource Enterprise CMDB
* Copyright (C) 2026 becon GmbH
*
* This program is free software: you can redistribute it and/or modify
* it under the terms of the GNU Affero General Public License as
* published by the Free Software Foundation, either version 3 of the
* License, or (at your option) any later version.
*
* This program is distributed in the hope that it will be useful,
* but WITHOUT ANY WARRANTY; without even the implied warranty of
* MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
* GNU Affero General Public License for more details.
*
* You should have received a copy of the GNU Affero General Public License
* along with this program. If not, see <https://www.gnu.org/licenses/>.
*/
import { ChangeDetectorRef, Component, Input, OnDestroy, OnInit, ViewChild, inject } from '@angular/core';
import { FormControl } from '@angular/forms';
import { NgbActiveModal, NgbModal } from '@ng-bootstrap/ng-bootstrap';

import { Observable, Subject } from 'rxjs';
import { finalize, takeUntil } from 'rxjs/operators';

import { CoreConfirmationModalComponent } from 'src/app/core/components/dialog/confirmation/core-confirmation-modal.component';
import { FullscreenModalService } from 'src/app/core/services/fullscreen-modal.service';
import { LoaderService } from 'src/app/core/services/loader.service';
import { ToastService } from 'src/app/layout/toast/toast.service';

import {
    INTERFACE_RELATION_TYPE_LABELS,
    InterfaceLinkView,
    InterfaceRelationType,
    InterfaceRowView,
    PortInterfaceLink
} from '../../models/interface-link.types';
import { CmdbPort } from '../../models/ports-overview.types';
import { InterfaceLinkService } from '../../services/interface-link.service';
import { InterfaceObjectLabelService } from '../../services/interface-object-label.service';
import { toInterfaceLinkView } from '../../utils/interface-row.util';
import { InterfaceCandidatePickerComponent } from '../interface-candidate-picker/interface-candidate-picker.component';
/* ------------------------------------------------------------------------------------------------------------------ */

/**
 * Where the option panel is rendered.
 *
 * The modal body is the element that scrolls, so a panel left inline is clipped by it and the user
 * has to scroll the dialog to read its own dropdown. The window sits outside that scroll box.
 */
const DROPDOWN_HOST = '.dg-modal-window';


/** One row of the list: the link, and the control its relation type is changed through. */
interface InterfaceLinkRow {
    view: InterfaceLinkView;
    relationControl: FormControl<InterfaceRelationType>;
}


/**
 * Manages the interface rows one port carries.
 *
 * A port can carry several - a bond member and the VLAN sub-interfaces over it - so this lists them
 * rather than editing a single value. Each write is its own request against its own route, so the
 * list is re-read after every one of them and nothing is held as a draft.
 */
@Component({
    selector: 'cmdb-interface-links-modal',
    templateUrl: './interface-links-modal.component.html',
    styleUrls: ['./interface-links-modal.component.scss'],
    standalone: false
})
export class InterfaceLinksModalComponent implements OnInit, OnDestroy {

    public readonly activeModal = inject(NgbActiveModal);

    private readonly interfaceLinkService = inject(InterfaceLinkService);
    private readonly objectLabels = inject(InterfaceObjectLabelService);
    private readonly modalService = inject(NgbModal);
    private readonly fullscreenModal = inject(FullscreenModalService);
    private readonly loaderService = inject(LoaderService);
    private readonly toastService = inject(ToastService);
    private readonly changesRef = inject(ChangeDetectorRef);

    /** The port whose interfaces are managed. */
    @Input() public port: CmdbPort | null = null;

    /** The object that port belongs to, named the way the user recognises it. */
    @Input() public objectLabel = '';

    /** Without it the dialog reads the links but offers no way to add or retype one. */
    @Input() public canEdit = false;

    /** Gates removal on its own: unlinking is what `port.delete` guards. */
    @Input() public canDelete = false;

    @ViewChild(InterfaceCandidatePickerComponent) private picker: InterfaceCandidatePickerComponent;

    /** Copied, because the select binds the list as a mutable one. */
    public readonly relationTypes = [...INTERFACE_RELATION_TYPE_LABELS];
    public readonly dropdownHost = DROPDOWN_HOST;
    public readonly isLoading$ = this.loaderService.isLoading$;

    /** What the port is linked to now, dangling links included. */
    public links: InterfaceLinkRow[] = [];

    /** The row picked to be linked next, kept in full so its addresses can be shown. */
    public selectedRow: InterfaceRowView | null = null;

    /** The relation type the next link is written with. */
    public readonly relationControl = new FormControl<InterfaceRelationType>(
        InterfaceRelationType.PHYSICAL,
        { nonNullable: true }
    );

    /** How many rows the port's object offers, so an empty list can say why it is empty. */
    public assignableTotal = 0;

    public hasError = false;

    /** The loader only appears after a delay, so the buttons themselves have to refuse a second click. */
    public isWriting = false;

    /** The link whose relation type is being changed. Only one row is in edit mode at a time. */
    public editingLinkId: number | null = null;

    /** Names of the objects holding the linked rows; the link routes answer with ids only. */
    public objectLabelsById = new Map<number, string>();

    /** Until the first page of candidates has answered, an empty list means "not read yet". */
    public hasReadCandidates = false;

    /** Set once anything was written, so the caller knows to reload the table. */
    private hasWritten = false;

    private readonly destroy$ = new Subject<void>();

/* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    public ngOnInit(): void {
        this.loadLinks();
    }


    public ngOnDestroy(): void {
        this.destroy$.next();
        this.destroy$.complete();
    }

/* ---------------------------------------------------- EVENTS ------------------------------------------------------ */

    public onSelectionChange(row: InterfaceRowView | null): void {
        this.selectedRow = row;
        this.changesRef.markForCheck();
    }


    public onAssignableTotalChange(total: number): void {
        this.assignableTotal = total;
        this.hasReadCandidates = true;
        this.changesRef.markForCheck();
    }


    public onLink(): void {
        if (!this.port || !this.selectedRow || !this.canEdit || this.isWriting) {
            return;
        }

        this.write(this.interfaceLinkService.createLink(this.port.public_id, {
            interface_object_id: this.selectedRow.interface_object_id,
            interface_multi_data_id: this.selectedRow.interface_multi_data_id,
            relation_type: this.relationControl.value
        }), 'Interface linked.');
    }


    /** Turns one row into its edit state. Leaving another row open would allow two pending changes. */
    public onStartEdit(row: InterfaceLinkRow): void {
        if (!this.canEdit || !row.view.interface) {
            return;
        }

        this.resetEditing();
        this.editingLinkId = row.view.publicId;
    }


    public onCancelEdit(row: InterfaceLinkRow): void {
        row.relationControl.setValue(row.view.relationType, { emitEvent: false });
        this.editingLinkId = null;
    }


    /** The row reference is re-sent unchanged: it is the link's identity, and a different one is refused. */
    public onSaveRelationType(row: InterfaceLinkRow): void {
        const relationType = row.relationControl.value;

        if (this.isWriting) {
            return;
        }

        if (!this.canEdit || !relationType || relationType === row.view.relationType) {
            this.onCancelEdit(row);
            return;
        }

        this.editingLinkId = null;

        this.write(this.interfaceLinkService.updateRelationType(row.view.publicId, {
            ...row.view.reference,
            relation_type: relationType
        }), 'Relation type changed.');
    }


    /** Unlinking is confirmed first: in a long list one stray click is otherwise a silent write. */
    public onUnlink(row: InterfaceLinkRow): void {
        if (!this.canDelete || this.isWriting) {
            return;
        }

        const label = row.view.interface?.label ?? `row ${ row.view.reference.interface_multi_data_id }`;

        // Deliberately not the delete dialog: nothing is deleted, and that wording is what makes a
        // user fear for the interface itself.
        const modal = this.modalService.open(CoreConfirmationModalComponent, this.fullscreenModal.withFullscreenContainer({
            size: 'lg',
            windowClass: 'dg-modal-window',
            backdropClass: 'dg-modal-window-backdrop'
        }));

        modal.componentInstance.title = 'Unlink interface';
        modal.componentInstance.message = `Do you want to unlink "${ label }" from this port?`;
        modal.componentInstance.confirmButtonText = 'Unlink';
        modal.componentInstance.confirmButtonClass = 'btn-danger';
        modal.componentInstance.warningMessage =
            'Neither the interface nor the port is removed - only the link between the two.';

        modal.result.then(
            (result) => {
                if (result === 'confirmed') {
                    this.write(this.interfaceLinkService.deleteLink(row.view.publicId), 'Interface unlinked.');
                }
            },
            () => {}
        );
    }


    public onClose(): void {
        // Emits only when something was stored, which is what the caller reloads on.
        if (this.hasWritten) {
            this.activeModal.close(true);
            return;
        }

        this.activeModal.dismiss();
    }

/* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    public get title(): string {
        return 'Manage interfaces';
    }


    public get subtitle(): string {
        const port = this.port?.name ?? '';

        return this.objectLabel && port ? `${ this.objectLabel } · ${ port }` : port || this.objectLabel;
    }


    /** The object a link points at, named the way the user recognises it. */
    public objectLabelOf(row: InterfaceLinkRow): string {
        const objectId = row.view.reference.interface_object_id;

        return this.objectLabelsById.get(objectId) ?? `Object #${ objectId }`;
    }


    public isEditing(row: InterfaceLinkRow): boolean {
        return this.editingLinkId === row.view.publicId;
    }


    /** A link whose row is gone can only be removed, so the list says so instead of offering an edit. */
    public get danglingCount(): number {
        return this.links.filter((row) => !row.view.interface).length;
    }


    /** Why the picker is empty: the port's object carries no interface left to link. */
    public get emptyPickerHint(): string {
        if (!this.hasReadCandidates || this.assignableTotal > 0) {
            return '';
        }

        return 'Every interface of this object is already linked to this port.';
    }

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    private loadLinks(): void {
        if (!this.port) {
            return;
        }

        this.loaderService.show();
        this.hasError = false;

        this.interfaceLinkService.getLinksOfPort(this.port.public_id)
            .pipe(
                takeUntil(this.destroy$),
                finalize(() => {
                    this.loaderService.hide();
                    this.changesRef.markForCheck();
                })
            )
            .subscribe({
                next: (links: PortInterfaceLink[]) => {
                    this.editingLinkId = null;
                    this.links = links.map((link) => this.toRow(toInterfaceLinkView(link)));
                    this.loadObjectLabels();
                },
                error: (err) => {
                    this.hasError = true;
                    this.toastService.error(err?.error?.message);
                }
            });
    }


    /** One request for every object of the port, and an unreadable one simply keeps its id. */
    private loadObjectLabels(): void {
        const objectIds = this.links.map((row) => row.view.reference.interface_object_id);

        this.objectLabels.labelsOf(objectIds)
            .pipe(takeUntil(this.destroy$))
            .subscribe((labels) => {
                this.objectLabelsById = labels;
                this.changesRef.markForCheck();
            });
    }


    private toRow(view: InterfaceLinkView): InterfaceLinkRow {
        return {
            view,
            relationControl: new FormControl<InterfaceRelationType>(view.relationType, { nonNullable: true })
        };
    }


    /** A reload replaces the rows, so an edit left open would point at a control nothing renders. */
    private resetEditing(): void {
        const open = this.links.find((row) => row.view.publicId === this.editingLinkId);

        open?.relationControl.setValue(open.view.relationType, { emitEvent: false });
        this.editingLinkId = null;
    }


    /** Every write reports the same way: re-read the list, so the dialog never shows a stale one. */
    private write(request: Observable<unknown>, successMessage: string): void {
        this.loaderService.show();
        this.isWriting = true;

        request
            .pipe(
                takeUntil(this.destroy$),
                finalize(() => {
                    this.isWriting = false;
                    this.loaderService.hide();
                    this.changesRef.markForCheck();
                })
            )
            .subscribe({
                next: () => {
                    this.hasWritten = true;
                    this.selectedRow = null;
                    this.toastService.success(successMessage);
                    this.picker?.reload();
                    this.loadLinks();
                },
                error: (err) => this.toastService.error(err?.error?.message)
            });
    }
}
