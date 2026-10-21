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
import { ChangeDetectorRef, Component, Input, OnDestroy, OnInit, inject } from '@angular/core';
import { NgbActiveModal } from '@ng-bootstrap/ng-bootstrap';

import { Subject, finalize, of, takeUntil } from 'rxjs';
import { catchError } from 'rxjs/operators';

import { LoaderService } from 'src/app/core/services/loader.service';
import { ToastService } from 'src/app/layout/toast/toast.service';

import { PortBulkDeletePreview, PortBulkDeleteResult, PortDeletePreviewEntry } from '../../models/port-bulk.types';
import { PortSelection } from '../../models/ports-overview.types';
import { PortService } from '../../services/port.service';
/* ------------------------------------------------------------------------------------------------------------------ */

/** One line of the impact list: a port and what the delete takes with it. */
interface DeletePreviewRow {
    name: string;
    connections: number;
    interfaceLinks: number;
}


/**
 * Deletes several ports at once, after saying what goes with them. Closes with `true` once they are.
 *
 * The preview is read on open because a port carries cabling and interface links the table does not
 * spell out. A preview that cannot be read does not block the delete: the delete route stays the
 * authority, and the dialog says the impact is unknown instead of claiming there is none.
 */
@Component({
    selector: 'cmdb-port-bulk-delete-modal',
    templateUrl: './port-bulk-delete-modal.component.html',
    styleUrls: ['./port-bulk-delete-modal.component.scss'],
    standalone: false
})
export class PortBulkDeleteModalComponent implements OnInit, OnDestroy {

    public readonly activeModal = inject(NgbActiveModal);
    private readonly portService = inject(PortService);
    private readonly loaderService = inject(LoaderService);
    private readonly toastService = inject(ToastService);
    private readonly changesRef = inject(ChangeDetectorRef);

    @Input() public objectId: number | null = null;

    /** The object the ports belong to, shown as the subtitle. */
    @Input() public objectLabel = '';

    /** The selected ports, in the order the table had them. */
    @Input() public ports: readonly PortSelection[] = [];

    public rows: DeletePreviewRow[] = [];
    public connectionCount = 0;
    public interfaceLinkCount = 0;

    /** True once the preview answered; until then the impact is not claimed either way. */
    public previewLoaded = false;
    public previewFailed = false;

    public readonly isLoading$ = this.loaderService.isLoading$;

    private readonly destroy$ = new Subject<void>();

/* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    public ngOnInit(): void {
        this.loadPreview();
    }

    public ngOnDestroy(): void {
        this.destroy$.next();
        this.destroy$.complete();
    }

/* ---------------------------------------------------- EVENTS ------------------------------------------------------ */

    public onConfirm(): void {
        if (this.objectId == null || !this.portIds.length) {
            return;
        }

        this.deletePorts(this.objectId);
    }

/* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    public get title(): string {
        return `Delete ${ this.ports.length } ports`;
    }


    /** Says in one line what else the delete removes, which is what the user is confirming. */
    public get impactMessage(): string {
        if (this.previewFailed) {
            return 'What else is removed could not be read. Any connection and interface link of these ports '
                + 'is deleted with them.';
        }

        const parts: string[] = [];

        if (this.connectionCount) {
            parts.push(`${ this.connectionCount } connection(s)`);
        }

        if (this.interfaceLinkCount) {
            parts.push(`${ this.interfaceLinkCount } interface link(s)`);
        }

        return parts.length
            ? `${ parts.join(' and ') } are deleted with these ports.`
            : 'These ports carry no connection and no interface link.';
    }


    /** Only the ports that take something with them are worth listing one by one. */
    public get affectedRows(): DeletePreviewRow[] {
        return this.rows.filter((row) => row.connections || row.interfaceLinks);
    }

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    private get portIds(): number[] {
        return this.ports.map((port) => port.publicId);
    }


    private loadPreview(): void {
        if (this.objectId == null || !this.portIds.length) {
            this.previewLoaded = true;
            return;
        }

        this.loaderService.show();

        this.portService.previewBulkDelete(this.objectId, this.portIds)
            .pipe(
                takeUntil(this.destroy$),
                catchError(() => {
                    this.previewFailed = true;
                    return of<PortBulkDeletePreview | null>(null);
                }),
                finalize(() => {
                    this.previewLoaded = true;
                    this.loaderService.hide();
                    this.changesRef.markForCheck();
                })
            )
            .subscribe((preview) => this.applyPreview(preview));
    }


    private applyPreview(preview: PortBulkDeletePreview | null): void {
        if (!preview) {
            return;
        }

        this.rows = (preview.ports ?? []).map((entry) => this.toRow(entry));
        this.connectionCount = preview.connection_ids?.length ?? 0;
        this.interfaceLinkCount = preview.interface_link_ids?.length ?? 0;
    }


    /** Falls back to the selected name: a port the preview does not name is still being deleted. */
    private toRow(entry: PortDeletePreviewEntry): DeletePreviewRow {
        const selected = this.ports.find((port) => port.publicId === entry.port_id);

        return {
            name: entry.name || selected?.name || `Port #${ entry.port_id }`,
            connections: entry.connection_ids?.length ?? 0,
            interfaceLinks: entry.interface_link_ids?.length ?? 0
        };
    }


    private deletePorts(objectId: number): void {
        this.loaderService.show();

        this.portService.bulkDeletePorts(objectId, this.portIds)
            .pipe(
                takeUntil(this.destroy$),
                finalize(() => this.loaderService.hide())
            )
            .subscribe({
                next: (result) => {
                    this.toastService.success(this.deletedMessage(result));
                    this.activeModal.close(true);
                },
                error: (err) => this.toastService.error(err?.error?.message)
            });
    }


    private deletedMessage(result: PortBulkDeleteResult | null): string {
        const deleted = result?.deleted ?? this.ports.length;
        const connections = result?.connection_ids?.length ?? 0;

        return connections
            ? `${ deleted } ports and ${ connections } connection(s) were successfully deleted!`
            : `${ deleted } ports were successfully deleted!`;
    }
}
