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
import { AbstractControl, FormControl, FormGroup, ValidationErrors, Validators } from '@angular/forms';
import { NgbActiveModal } from '@ng-bootstrap/ng-bootstrap';

import { Subject, finalize, takeUntil } from 'rxjs';

import { ExtendableOptionCatalogService } from 'src/app/core/services/extendable-option-catalog.service';
import { LoaderService } from 'src/app/core/services/loader.service';
import { FieldOption } from 'src/app/framework/models/cmdb-section-template';
import { PortOptionType } from 'src/app/framework/models/port-option-type';
import { ToastService } from 'src/app/layout/toast/toast.service';

import { CmdbPort, PORT_OPTION_TYPES, PortPayload } from '../../models/ports-overview.types';
import { PortService } from '../../services/port.service';
/* ------------------------------------------------------------------------------------------------------------------ */

/** The backend refuses a blank name, so spaces alone do not count as one. */
function nonBlank(control: AbstractControl): ValidationErrors | null {
    return (control.value ?? '').trim() ? null : { required: true };
}


/** Creates or edits a single port. Closes with `true` once it is stored. */
@Component({
    selector: 'cmdb-port-form-modal',
    templateUrl: './port-form-modal.component.html',
    styleUrls: ['./port-form-modal.component.scss'],
    standalone: false
})
export class PortFormModalComponent implements OnInit, OnDestroy {

    public readonly activeModal = inject(NgbActiveModal);
    private readonly portService = inject(PortService);
    private readonly optionCatalog = inject(ExtendableOptionCatalogService);
    private readonly loaderService = inject(LoaderService);
    private readonly toastService = inject(ToastService);
    private readonly changesRef = inject(ChangeDetectorRef);

    @Input() public objectId: number | null = null;

    /** The object the port belongs to, shown as the subtitle. */
    @Input() public objectLabel = '';

    /** The port being edited, or null to create a new one. */
    @Input() public port: CmdbPort | null = null;

    public readonly form = new FormGroup({
        name: new FormControl<string>('', [nonBlank, Validators.maxLength(255)]),
        portNumber: new FormControl<string>('', [Validators.pattern(/^\d+$/)]),
        status: new FormControl<string | null>(null),
        portType: new FormControl<string | null>(null),
        speed: new FormControl<string | null>(null),
        description: new FormControl<string>('', [Validators.maxLength(255)])
    });

    public statusOptions: FieldOption[] = [];
    public portTypeOptions: FieldOption[] = [];
    public speedOptions: FieldOption[] = [];

    public readonly isLoading$ = this.loaderService.isLoading$;

    private readonly destroy$ = new Subject<void>();

/* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    public ngOnInit(): void {
        this.prefillFromPort();
        this.loadOptions();
    }

    public ngOnDestroy(): void {
        this.destroy$.next();
        this.destroy$.complete();
    }

/* ---------------------------------------------------- EVENTS ------------------------------------------------------ */

    public onSubmit(): void {
        if (this.objectId == null) {
            return;
        }

        if (this.form.invalid) {
            this.form.markAllAsTouched();
            this.changesRef.markForCheck();
            return;
        }

        this.save(this.buildPayload(this.objectId));
    }

/* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    public get isEdit(): boolean {
        return this.port != null;
    }


    public get title(): string {
        return this.isEdit ? 'Edit port' : 'Add port';
    }


    public get submitLabel(): string {
        return this.isEdit ? 'Save changes' : 'Create port';
    }


    /** A message is only worth showing once the user has left the field. */
    public errorOf(controlName: 'name' | 'portNumber' | 'description'): string {
        const control = this.form.controls[controlName];

        if (!control.touched || control.valid) {
            return '';
        }

        if (control.hasError('required')) {
            return 'A port needs a name.';
        }

        if (control.hasError('pattern')) {
            return 'The port number has to be a whole number.';
        }

        return 'This value is too long.';
    }

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    /** The form holds every value as a string, which is also what the selects bind to. */
    private prefillFromPort(): void {
        if (!this.port) {
            return;
        }

        this.form.patchValue({
            name: this.port.name ?? '',
            portNumber: this.port.port_number == null ? '' : String(this.port.port_number),
            status: this.asOptionValue(this.port.status),
            portType: this.asOptionValue(this.port.port_type),
            speed: this.asOptionValue(this.port.speed),
            description: this.port.description ?? ''
        });
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


    private save(payload: PortPayload): void {
        const request = this.port
            ? this.portService.updatePort(this.port.public_id, payload)
            : this.portService.createPort(payload);
        const message = this.port ? 'Port was successfully updated!' : 'Port was successfully created!';

        this.loaderService.show();

        request
            .pipe(
                takeUntil(this.destroy$),
                finalize(() => this.loaderService.hide())
            )
            .subscribe({
                next: () => {
                    this.toastService.success(message);
                    this.activeModal.close(true);
                },
                error: (err) => this.toastService.error(err?.error?.message)
            });
    }


    /** An untouched select and an empty number have to reach the route as null, not as ''. */
    private buildPayload(objectId: number): PortPayload {
        return {
            object_id: objectId,
            name: this.trimmed('name'),
            port_number: this.asNumber(this.trimmed('portNumber')),
            status: this.asNumber(this.form.controls.status.value),
            port_type: this.asNumber(this.form.controls.portType.value),
            speed: this.asNumber(this.form.controls.speed.value),
            description: this.trimmed('description') || null
        };
    }


    private trimmed(controlName: 'name' | 'portNumber' | 'description'): string {
        return (this.form.controls[controlName].value ?? '').trim();
    }


    private asNumber(value: string | null): number | null {
        return value === null || value === '' ? null : Number(value);
    }


    private asOptionValue(optionId: number | null): string | null {
        return optionId == null ? null : String(optionId);
    }
}
