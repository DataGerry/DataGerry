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
import { FormControl, FormGroup, Validators } from '@angular/forms';
import { NgbActiveModal } from '@ng-bootstrap/ng-bootstrap';

import { Subject, finalize, takeUntil } from 'rxjs';

import { ExtendableOptionCatalogService } from 'src/app/core/services/extendable-option-catalog.service';
import { LoaderService } from 'src/app/core/services/loader.service';
import { FieldOption } from 'src/app/framework/models/cmdb-section-template';
import { PortOptionType } from 'src/app/framework/models/port-option-type';
import { ToastService } from 'src/app/layout/toast/toast.service';

import { PortBulkUpdateValues } from '../../models/port-bulk.types';
import { PORT_OPTION_TYPES, PortSelection } from '../../models/ports-overview.types';
import { PortService } from '../../services/port.service';
/* ------------------------------------------------------------------------------------------------------------------ */

/** Description is the only free-text field of a port; the backend stores it unbounded. */
const DESCRIPTION_MAX_LENGTH = 255;

/** How many port names the summary shows as chips before it counts the rest. */
const NAMED_PORTS_LIMIT = 8;

/**
 * Where the option panels are rendered.
 *
 * The modal body is the element that scrolls, so a panel left inline is clipped by it and the user
 * has to scroll the dialog to read its own dropdown. The window sits outside that scroll box.
 */
const DROPDOWN_HOST = '.dg-modal-window';

/** The four fields the bulk route accepts, by their control name. */
type BulkField = 'status' | 'portType' | 'speed' | 'description';


/**
 * Writes the same values onto every selected port. Closes with `true` once they are stored.
 *
 * Each field is opt-in: a field left switched off is not part of the request at all, and a field
 * switched on but left empty clears itself on every selected port. Nothing else can be edited in
 * bulk - a name or a port number is unique per port, so it stays a single-port edit.
 */
@Component({
    selector: 'cmdb-port-bulk-edit-modal',
    templateUrl: './port-bulk-edit-modal.component.html',
    styleUrls: ['./port-bulk-edit-modal.component.scss'],
    standalone: false
})
export class PortBulkEditModalComponent implements OnInit, OnDestroy {

    public readonly activeModal = inject(NgbActiveModal);
    private readonly portService = inject(PortService);
    private readonly optionCatalog = inject(ExtendableOptionCatalogService);
    private readonly loaderService = inject(LoaderService);
    private readonly toastService = inject(ToastService);
    private readonly changesRef = inject(ChangeDetectorRef);

    @Input() public objectId: number | null = null;

    /** The object the ports belong to, shown as the subtitle. */
    @Input() public objectLabel = '';

    /** The selected ports, in the order the table had them. */
    @Input() public ports: readonly PortSelection[] = [];

    // Disabled is the resting state: a field only joins the request once its switch is on.
    public readonly form = new FormGroup({
        status: new FormControl<string | null>({ value: null, disabled: true }),
        portType: new FormControl<string | null>({ value: null, disabled: true }),
        speed: new FormControl<string | null>({ value: null, disabled: true }),
        description: new FormControl<string>(
            { value: '', disabled: true },
            [Validators.maxLength(DESCRIPTION_MAX_LENGTH)]
        )
    });

    public readonly dropdownHost = DROPDOWN_HOST;

    public statusOptions: FieldOption[] = [];
    public portTypeOptions: FieldOption[] = [];
    public speedOptions: FieldOption[] = [];

    public readonly isLoading$ = this.loaderService.isLoading$;

    private readonly destroy$ = new Subject<void>();

/* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    public ngOnInit(): void {
        this.loadOptions();
    }

    public ngOnDestroy(): void {
        this.destroy$.next();
        this.destroy$.complete();
    }

/* ---------------------------------------------------- EVENTS ------------------------------------------------------ */

    /** The value is kept while a field is off, so an accidental toggle costs nothing. */
    public onToggleField(field: BulkField, enabled: boolean): void {
        const control = this.form.controls[field];

        if (enabled) {
            control.enable();
        } else {
            control.disable();
        }

        this.changesRef.markForCheck();
    }


    public onSubmit(): void {
        if (this.objectId == null || !this.portIds.length || !this.hasChanges) {
            return;
        }

        if (this.form.invalid) {
            this.form.markAllAsTouched();
            this.changesRef.markForCheck();
            return;
        }

        this.save(this.objectId, this.buildValues());
    }

/* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    public get title(): string {
        return `Edit ${ this.ports.length } ports`;
    }


    /** Nothing switched on means nothing to write, which is what keeps the submit button off. */
    public get hasChanges(): boolean {
        return (['status', 'portType', 'speed', 'description'] as BulkField[])
            .some((field) => this.form.controls[field].enabled);
    }


    public isFieldEnabled(field: BulkField): boolean {
        return this.form.controls[field].enabled;
    }


    /** The first names in full, then a count - a selection of a whole panel is otherwise unreadable. */
    public get visiblePorts(): readonly PortSelection[] {
        return this.ports.slice(0, NAMED_PORTS_LIMIT);
    }


    public get remainingPortCount(): number {
        return Math.max(this.ports.length - NAMED_PORTS_LIMIT, 0);
    }


    public get descriptionError(): string {
        const control = this.form.controls.description;

        return control.touched && control.invalid ? 'This description is too long.' : '';
    }

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    private get portIds(): number[] {
        return this.ports.map((port) => port.publicId);
    }


    /** One request for all three lists, then cached by the catalog. */
    private loadOptions(): void {
        this.loaderService.show();

        this.optionCatalog.optionsForTypes(PORT_OPTION_TYPES)
            .pipe(
                takeUntil(this.destroy$),
                finalize(() => {
                    this.loaderService.hide();
                    this.changesRef.markForCheck();
                })
            )
            .subscribe({
                next: (optionsByType) => {
                    this.statusOptions = optionsByType.get(PortOptionType.STATUS) ?? [];
                    this.portTypeOptions = optionsByType.get(PortOptionType.PORT_TYPE) ?? [];
                    this.speedOptions = optionsByType.get(PortOptionType.SPEED) ?? [];
                },
                error: (err) => this.toastService.error(err?.error?.message)
            });
    }


    /** Only the switched-on fields become keys; an empty one reaches the route as null and clears. */
    private buildValues(): PortBulkUpdateValues {
        const values: PortBulkUpdateValues = {};

        if (this.isFieldEnabled('status')) {
            values.status = this.asNumber(this.form.controls.status.value);
        }

        if (this.isFieldEnabled('portType')) {
            values.port_type = this.asNumber(this.form.controls.portType.value);
        }

        if (this.isFieldEnabled('speed')) {
            values.speed = this.asNumber(this.form.controls.speed.value);
        }

        if (this.isFieldEnabled('description')) {
            values.description = (this.form.controls.description.value ?? '').trim() || null;
        }

        return values;
    }


    private save(objectId: number, values: PortBulkUpdateValues): void {
        const portIds = this.portIds;

        this.loaderService.show();

        this.portService.bulkUpdatePorts(objectId, { port_ids: portIds, values })
            .pipe(
                takeUntil(this.destroy$),
                finalize(() => this.loaderService.hide())
            )
            .subscribe({
                next: () => {
                    this.toastService.success(`${ portIds.length } ports were successfully updated!`);
                    this.activeModal.close(true);
                },
                error: (err) => this.toastService.error(err?.error?.message)
            });
    }


    private asNumber(value: string | null): number | null {
        return value === null || value === '' ? null : Number(value);
    }
}
