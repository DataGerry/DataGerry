import { Component } from '@angular/core';
import { UntypedFormControl, UntypedFormGroup, Validators } from '@angular/forms';
import { finalize } from 'rxjs';
import { LoaderService } from 'src/app/core/services/loader.service';
import { ImportService } from '../../services/import.service';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { NgbModal } from '@ng-bootstrap/ng-bootstrap';
import { ImportSummaryModalComponent } from '../import-summary-dialog/import-summary-dialog.component';

@Component({
    selector: 'cmdb-risk-import',
    templateUrl: './risk-import.component.html',
    standalone: false
})
export class ImportRiskComponent {
    public fileForm: UntypedFormGroup;
    public fileName: string = 'Choose CSV file';
    public isLoading$ = this.loaderService.isLoading$;
    public showInstructions = false;

    importInstructions = {
        title: 'Importing Risks via CSV',
        description: 'You can import multiple Risks using a CSV file. Please follow the structure and guidelines below to ensure successful import.',
        headers: [
            { header: 'name', type: 'string', required: 'Yes (*)', description: 'The name or title of the Risk' },
            { header: 'risk_type', type: 'string', required: 'No (*)', description: 'The type of the Risk (Allowed values: THREAT_X_VULNERABILITY, THREAT, EVENT)' },
            { header: 'protection_goals', type: 'string', required: 'No', description: 'The related protection goals (e.g., Confidentiality, Integrity, Availability); use comma-separated values' },
            { header: 'threats', type: 'string', required: 'No', description: 'Associated Threats by name; use comma-separated values' },
            { header: 'vulnerabilities', type: 'string', required: 'No', description: 'Linked Vulnerabilities by name; use comma-separated values' },
            { header: 'identifier', type: 'string', required: 'No', description: 'An identifier for the Risk' },
            { header: 'consequences', type: 'string', required: 'No', description: 'Potential consequences if the Risk materializes' },
            { header: 'description', type: 'string', required: 'No', description: 'A detailed explanation or context of the Risk' }
        ],
        notes: `The required fields and other conditions depend on the 'risk_type' of the Risk:\n
      THREAT_X_VULNERABILITY
      - threats is required
      - vulnerabilities is required
      - consequences need to be empty
      
      THREAT
      - threats is required
      - vulnerabilities need to be empty
      - consequences need to be empty
      
      EVENT
      - threats need to be empty
      - vulnerabilities need to be empty
      - consequences is required
      - description is required`,
        mappings: 'The \'protection_goals\', \'threats\' and \'vulnerabilities\' value is matched against existing ones by name.\n\nCase sensitive: "Source" is not equal to "source".\n\nIf a matching does not exist, it will be automatically created in the database.',
        duplicates: 'The system checks for existing Risks using case-sensitive comparison across all fields.\n\nA Risk is only created if there is no exact match already in the database.\n\nRe-importing the same CSV file will not result in duplicates.',
        exampleCsv: `name;risk_type;protection_goals;threats;vulnerabilities;identifier;consequences;description
      Risk1;THREAT;Confidentiality,Integrity;Fire,Water;;Identifier1;;Description1
      Risk2;EVENT;Integrity;;;Identifier2;Consequences2;Description2`
    };


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

    importRisk(): void {
        if (this.fileForm.invalid) {
            this.toastService.error('Please select a CSV file.');
            return;
        }

        const file = this.file.value;
        this.loaderService.show();
        this.importService
            .importRiskFile(file)
            .pipe(finalize(() => this.loaderService.hide()))
            .subscribe({
                next: (response) => {
                    const modalRef = this.modalService.open(ImportSummaryModalComponent, { size: 'lg' });
                    modalRef.componentInstance.summary = response;
                },
                error: (error) => {
                    this.toastService.error(error?.error?.message);
                }
            });
    }
}