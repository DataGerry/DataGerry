import { Component, OnInit, Output } from '@angular/core';
import { TypeService } from '../../framework/services/type.service';
import { CmdbType } from '../../framework/models/cmdb-type';
import { UntypedFormControl, UntypedFormGroup, Validators } from '@angular/forms';
import { DatePipe } from '@angular/common';
import { FileSaverService } from 'ngx-filesaver';
import { FileService } from '../export.service';
import { LoaderService } from 'src/app/core/services/loader.service';
import { finalize } from 'rxjs';

@Component({
    selector: 'cmdb-export-types',
    templateUrl: './export-types.component.html',
    styleUrls: ['./export-types.component.scss'],
    standalone: false
})
export class ExportTypesComponent implements OnInit {

    public typeList: CmdbType[] = [];
    public formatList: any[] = [{ id: 0, label: 'json', icon: 'file-code' }];
    public formExport: UntypedFormGroup;
    public isSubmitted: boolean;
    public isLoading$ = this.loaderService.isLoading$;

    constructor(private typeService: TypeService, private exportService: FileService,
        private datePipe: DatePipe, private fileSaverService: FileSaverService,  private loaderService: LoaderService) {
        this.formExport = new UntypedFormGroup({
            type: new UntypedFormControl(null, Validators.required),
            format: new UntypedFormControl(null, Validators.required)
        });
    }


    public ngOnInit(): void {
        this.loaderService.show();
        this.typeService.getTypeList().pipe(finalize(() => this.loaderService.hide())).subscribe((typeList: CmdbType[]) => {
            this.typeList = typeList;
        });
    }


    get type() {
        return this.formExport.get('type');
    }


    get format() {
        return this.formExport.get('format');
    }


    private resetForm() {
        this.formExport.reset();
        this.formExport.markAsPristine();
        this.formExport.markAsUntouched();
        this.formExport.markAsDirty();
    }


    public export() {
        this.isSubmitted = false;
        if (!this.formExport.valid) {
            return false;
        }


        const typeID = this.formExport.get('type').value;
        const fileExtension: any = this.formExport.get('format').value;

        // Reset FormGroup
        this.resetForm();

        if (fileExtension != null && typeID != null) {
            this.loaderService.show();
            this.exportService.callExportTypeRoute('export/type/' + typeID.toString()).pipe(finalize(() => this.loaderService.hide()))
                .subscribe(res => this.downLoadFile(res));
        }
    }


    public downLoadFile(data: any) {
        const timestamp = this.datePipe.transform(new Date(), 'MM_dd_yyyy_hh_mm_ss');
        this.fileSaverService.save(data.body, timestamp + '.json');
    }

}