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
import { DatePipe } from '@angular/common';

import { TypeService } from '../../framework/services/type.service';
import { FileSaverService } from 'ngx-filesaver';
import { FileService } from '../export.service';

import { CmdbType } from '../../framework/models/cmdb-type';
import { SupportedExporterExtension } from './model/supported-exporter-extension';
import { CollectionParameters } from '../../services/models/api-parameter';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { LoaderService } from 'src/app/core/services/loader.service';
import { finalize } from 'rxjs';
/* ------------------------------------------------------------------------------------------------------------------ */
@Component({
    selector: 'cmdb-export-objects',
    templateUrl: './export-objects.component.html',
    styleUrls: ['./export-objects.component.scss'],
    standalone: false
})
export class ExportObjectsComponent implements OnInit {
    public typeList: CmdbType[];
    public formatList: SupportedExporterExtension[] = [];
    public formExport: UntypedFormGroup;
    public isVisible: boolean;
    public isLoading$ = this.loaderService.isLoading$;

    /** Export formats (class names) for which a human-readable export is supported by the backend. */
    private readonly humanReadableFormats: string[] = ['CsvExportFormat', 'XlsxExportFormat'];

    /* ------------------------------------------------------------------------------------------------------------------ */
    /*                                                     LIFE CYCLE                                                     */
    /* ------------------------------------------------------------------------------------------------------------------ */
    constructor(
        private exportService: FileService,
        private datePipe: DatePipe,
        private typeService: TypeService,
        private fileSaverService: FileSaverService,
        private toastService: ToastService,
        private loaderService: LoaderService,
    ) {
        this.formExport = new UntypedFormGroup({
            type: new UntypedFormControl(null, Validators.required),
            format: new UntypedFormControl(null, Validators.required),
            humanReadable: new UntypedFormControl(false)
        });
    }


    ngOnInit() {
        this.loaderService.show();
        this.typeService.getTypeList().pipe(finalize(() => this.loaderService.hide())).subscribe(data => {
            this.typeList = data;
        });

        this.exportService.callFileFormatRoute().subscribe(data => {
            this.formatList = data;
        });
    }

    /* ------------------------------------------------- GETTER / SETTER ------------------------------------------------ */

    get type() {
        return this.formExport.get('type');
    }


    get format() {
        return this.formExport.get('format');
    }


    get humanReadable() {
        return this.formExport.get('humanReadable');
    }


    get isHumanReadableFormat(): boolean {
        return this.humanReadableFormats.includes(this.format?.value);
    }

    /* ------------------------------------------------- HELPER METHODS ------------------------------------------------- */

    private resetForm() {
        this.formExport.reset();
        this.formExport.markAsPristine();
        this.formExport.markAsUntouched();
        this.formExport.markAsDirty();
    }


    public exportObjectByTypeID() {
        if (this.formExport.invalid) {
            this.toastService.error('Please select the required fields');
            return;
        }

        const typeID = this.formExport.get('type').value;
        const fileExtension: any = this.formExport.get('format').value;
        const humanReadable = this.isHumanReadableFormat && this.formExport.get('humanReadable').value;

        // Reset FormGroup
        this.resetForm();

        if (fileExtension != null && typeID != null) {
            const filter = { type_id: typeID };
            const optional: any = { classname: fileExtension, zip: false };

            if (humanReadable) {
                optional.human_readable = true;
            }

            const exportAPI: CollectionParameters = { filter, optional, order: 1, sort: 'public_id' };

            this.loaderService.show();
            this.exportService.callExportRoute(exportAPI)
            .pipe(finalize(()=>   this.loaderService.hide()))
                .subscribe({
                    next: res => this.downLoadFile(res, fileExtension),
                    error: e => {
                        this.toastService.error(e?.error?.message);
                    }
                })
        }
    }


    public downLoadFile(data: any, exportType: any) {
        this.isVisible = false;
        const timestamp = this.datePipe.transform(new Date(), 'MM_dd_yyyy_hh_mm_ss');
        const extension = this.formatList.find(x => x.extension === exportType);
        this.fileSaverService.save(data.body, timestamp + '.' + extension.label);
    }
}
