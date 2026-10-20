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
import { Component, OnInit } from '@angular/core';
import { UntypedFormControl, UntypedFormGroup, Validators } from '@angular/forms';
import { HttpResponse } from '@angular/common/http';

import { finalize } from 'rxjs';

import { TypeService } from '../../framework/services/type.service';
import { FileService } from '../export.service';
import { LoaderService } from '../../core/services/loader.service';
import { ExportDownloadService } from '../../core/services/export-download.service';
import { ToastService } from '../../layout/toast/toast.service';

import { CmdbType } from '../../framework/models/cmdb-type';
import { ExportKind } from '../../core/models/export-download.model';
import { ExportTypeOption } from '../export-types/export-type-option.model';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'cmdb-export-csv-templates',
    templateUrl: './export-csv-templates.component.html',
    styleUrls: ['./export-csv-templates.component.scss'],
    standalone: false
})
export class ExportCsvTemplatesComponent implements OnInit {

    public typeOptions: ExportTypeOption[] = [];
    public formExport: UntypedFormGroup;
    public isSubmitted = false;
    public isLoading$ = this.loaderService.isLoading$;

    constructor(
        private typeService: TypeService,
        private exportService: FileService,
        private exportDownloadService: ExportDownloadService,
        private toastService: ToastService,
        private loaderService: LoaderService
    ) {
        this.formExport = new UntypedFormGroup({
            type: new UntypedFormControl(null, Validators.required)
        });
    }

/* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    public ngOnInit(): void {
        this.loaderService.show();

        this.typeService.getTypeList()
            .pipe(finalize(() => this.loaderService.hide()))
            .subscribe({
                next: (typeList: CmdbType[]) => {
                    this.typeOptions = (typeList ?? []).map((type: CmdbType) => ({
                        public_id: type.public_id,
                        label: `${type.label} #${type.public_id}`
                    }));
                },
                error: () => this.toastService.error('The object types could not be loaded.')
            });
    }

/* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    get type() {
        return this.formExport.get('type');
    }


    public exportTemplate(): void {
        this.isSubmitted = true;

        if (this.formExport.invalid) {
            return;
        }

        const typeID: number = this.type.value;

        this.loaderService.show();

        this.exportService.callExportCsvTemplateRoute(typeID)
            .pipe(finalize(() => this.loaderService.hide()))
            .subscribe({
                next: (response: HttpResponse<Blob>) => this.downloadTemplate(response),
                error: () => this.toastService.error('The CSV template could not be exported.')
            });
    }

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    private downloadTemplate(response: HttpResponse<Blob>): void {
        this.exportDownloadService.save(response, { kind: ExportKind.CsvTemplate, extension: 'csv' });
    }
}
