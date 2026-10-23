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
* along with this program.  If not, see <https://www.gnu.org/licenses/>.
*/
import { ChangeDetectionStrategy, Component, DestroyRef, inject } from '@angular/core';
import { AsyncPipe } from '@angular/common';
import { HttpResponse } from '@angular/common/http';
import { FormControl, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';

import { finalize } from 'rxjs';

import { CoreModule } from '../../core/core.module';
import { LayoutModule } from '../../layout/layout.module';

import { FileService } from '../export.service';
import { LoaderService } from '../../core/services/loader.service';
import { ExportDownloadService } from '../../core/services/export-download.service';
import { ToastService } from '../../layout/toast/toast.service';

import { ExportKind } from '../../core/models/export-download.model';
import {
    CONFIGURATION_EXPORT_DESCRIPTION_MAX_LENGTH,
    CONFIGURATION_EXPORT_FILENAME_MAX_LENGTH,
    CONFIGURATION_EXPORT_NAME_MAX_LENGTH,
    ConfigurationExportRequest
} from '../../core/models/configuration-transfer.model';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'cmdb-export-data-model',
    templateUrl: './export-data-model.component.html',
    styleUrls: ['./export-data-model.component.scss'],
    imports: [AsyncPipe, ReactiveFormsModule, CoreModule, LayoutModule],
    changeDetection: ChangeDetectionStrategy.OnPush
})
export class ExportDataModelComponent {

    private readonly exportService = inject(FileService);
    private readonly exportDownloadService = inject(ExportDownloadService);
    private readonly toastService = inject(ToastService);
    private readonly loaderService = inject(LoaderService);
    private readonly destroyRef = inject(DestroyRef);

    public readonly isLoading$ = this.loaderService.isLoading$;

    public readonly exportForm = new FormGroup({
        // The pattern rejects a name made of blanks only.
        name: new FormControl('', {
            nonNullable: true,
            validators: [Validators.required, Validators.pattern(/\S/), Validators.maxLength(CONFIGURATION_EXPORT_NAME_MAX_LENGTH)]
        }),
        description: new FormControl('', {
            nonNullable: true,
            validators: [Validators.maxLength(CONFIGURATION_EXPORT_DESCRIPTION_MAX_LENGTH)]
        }),
        filename: new FormControl('', {
            nonNullable: true,
            validators: [Validators.maxLength(CONFIGURATION_EXPORT_FILENAME_MAX_LENGTH)]
        })
    });

/* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    public exportDataModel(): void {
        if (this.exportForm.invalid) {
            this.exportForm.markAllAsTouched();
            return;
        }

        this.loaderService.show();

        this.exportService.callExportDataModelRoute(this.buildExportRequest())
            .pipe(
                finalize(() => this.loaderService.hide()),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe({
                next: (response: HttpResponse<Blob>) => this.downloadDataModel(response),
                error: () => this.toastService.error('The data model could not be exported.')
            });
    }

    public nameError(): string {
        const control = this.exportForm.controls.name;

        if (!control.touched) {
            return '';
        }

        if (control.hasError('required') || control.hasError('pattern')) {
            return 'Name is required.';
        }

        return control.hasError('maxlength') ? `Name can have at most ${ CONFIGURATION_EXPORT_NAME_MAX_LENGTH } characters.` : '';
    }


    public descriptionError(): string {
        return this.maxLengthError('description', 'Description', CONFIGURATION_EXPORT_DESCRIPTION_MAX_LENGTH);
    }


    public filenameError(): string {
        return this.maxLengthError('filename', 'File name', CONFIGURATION_EXPORT_FILENAME_MAX_LENGTH);
    }

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    /** An empty file name lets the backend generate one. */
    private buildExportRequest(): ConfigurationExportRequest {
        const { name, description, filename } = this.exportForm.getRawValue();

        return {
            name: name.trim(),
            description: description.trim(),
            filename: filename.trim() || null
        };
    }


    private maxLengthError(field: 'description' | 'filename', label: string, maxLength: number): string {
        const control = this.exportForm.controls[field];

        return control.touched && control.hasError('maxlength') ? `${ label } can have at most ${ maxLength } characters.` : '';
    }


    private downloadDataModel(response: HttpResponse<Blob>): void {
        this.exportDownloadService.save(response, { kind: ExportKind.Configuration, extension: 'json' });
    }
}
