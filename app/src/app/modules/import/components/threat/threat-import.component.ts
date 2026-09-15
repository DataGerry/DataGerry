import { Component } from '@angular/core';
import { UntypedFormControl, UntypedFormGroup, Validators } from '@angular/forms';
import { finalize } from 'rxjs';
import { LoaderService } from 'src/app/core/services/loader.service';
import { ImportService } from '../../services/import.service';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { NgbModal } from '@ng-bootstrap/ng-bootstrap';
import { ImportSummaryModalComponent } from '../import-summary-dialog/import-summary-dialog.component';

@Component({
    selector: 'cmdb-threat-import',
    templateUrl: './threat-import.component.html',
    standalone: false
})
export class ImportThreatComponent {
    public fileForm: UntypedFormGroup;
    public fileName: string = 'Choose CSV file';
    public isLoading$ = this.loaderService.isLoading$;
    showInstructions = false;


    constructor(
        private importService: ImportService,
        private loaderService: LoaderService,
        private toastService: ToastService,
        private modalService: NgbModal
        
    ) {
        this.fileForm = new UntypedFormGroup({
            file: new UntypedFormControl(null, Validators.required)
        });
    }

    get file() {
        return this.fileForm.get('file');
    }

    selectFile(files: FileList): void {
        if (files.length > 0) {
            const file = files[0];
            this.file.setValue(file);
            this.fileName = file.name;
        }
    }

    importThreat(): void {
        if (this.fileForm.invalid) {
            this.toastService.error('Please select a CSV file.');
            return;
        }

        const file = this.file.value;
        this.loaderService.show();
        this.importService
            .importThreatFile(file)
            .pipe(finalize(() => this.loaderService.hide()))
            .subscribe({
                next: (response) => {
                    const modalRef = this.modalService.open(ImportSummaryModalComponent, {
                        size: 'xl',
                        windowClass: 'dg-modal-window',
                        backdropClass: 'dg-modal-window-backdrop'
                    });
                    modalRef.componentInstance.summary = response;
                },
                error: (error) => {
                    this.toastService.error(error?.error?.message);
                }
            });
    }
}