import { Component, OnInit } from '@angular/core';
import { TypeService } from '../../framework/services/type.service';
import { CmdbType } from '../../framework/models/cmdb-type';
import { UntypedFormControl, UntypedFormGroup, Validators } from '@angular/forms';
import { HttpResponse } from '@angular/common/http';
import { FileService } from '../export.service';
import { LoaderService } from 'src/app/core/services/loader.service';
import { ExportDownloadService } from 'src/app/core/services/export-download.service';
import { ExportKind } from 'src/app/core/models/export-download.model';
import { finalize } from 'rxjs';
import { ExportTypeOption } from './export-type-option.model';

@Component({
    selector: 'cmdb-export-types',
    templateUrl: './export-types.component.html',
    styleUrls: ['./export-types.component.scss'],
    standalone: false
})
export class ExportTypesComponent implements OnInit {

    public typeOptions: ExportTypeOption[] = [];
    public formatList: any[] = [{ id: 0, label: 'json', icon: 'file-code' }];
    public formExport: UntypedFormGroup;
    public isSubmitted: boolean;
    public isLoading$ = this.loaderService.isLoading$;

    constructor(private typeService: TypeService, private exportService: FileService,
        private exportDownloadService: ExportDownloadService, private loaderService: LoaderService) {
        this.formExport = new UntypedFormGroup({
            types: new UntypedFormControl([], Validators.required),
            format: new UntypedFormControl(null, Validators.required)
        });
    }

/* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    public ngOnInit(): void {
        this.loaderService.show();
        this.typeService.getTypeList().pipe(finalize(() => this.loaderService.hide())).subscribe((typeList: CmdbType[]) => {
            this.typeOptions = (typeList ?? []).map((type: CmdbType) => ({
                public_id: type.public_id,
                label: `${type.label} #${type.public_id}`
            }));
        });
    }

/* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    get types() {
        return this.formExport.get('types');
    }


    get format() {
        return this.formExport.get('format');
    }


    public export() {
        this.isSubmitted = true;

        if (!this.formExport.valid) {
            return false;
        }

        const typeIDs: number[] = this.types.value ?? [];
        const fileExtension: any = this.format.value;

        // An empty selection would collapse the route onto /export/type/ and export the whole catalogue
        if (typeIDs.length === 0 || fileExtension == null) {
            return false;
        }

        // Reset FormGroup
        this.resetForm();

        this.loaderService.show();
        this.exportService.callExportTypeRoute('export/type/' + typeIDs.join(','))
            .pipe(finalize(() => this.loaderService.hide()))
            .subscribe(res => this.downLoadFile(res));
    }


    public downLoadFile(response: HttpResponse<Blob>) {
        this.exportDownloadService.save(response, { kind: ExportKind.Types, extension: 'json' });
    }

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    private resetForm() {
        this.formExport.reset({ types: [], format: null });
        this.formExport.markAsPristine();
        this.formExport.markAsUntouched();
        this.isSubmitted = false;
    }
}
