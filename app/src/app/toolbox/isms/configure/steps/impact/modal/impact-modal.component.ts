import { Location } from '@angular/common';
import { Component, inject, Input, OnInit } from '@angular/core';
import {
    FormBuilder,
    FormGroup,
    Validators,
} from '@angular/forms';
import { NgbActiveModal, NgbModal } from '@ng-bootstrap/ng-bootstrap';
import { finalize } from 'rxjs/operators';
import { CoreWarningModalComponent } from 'src/app/core/components/dialog/core-warning-modal/core-warning-modal.component';

import { ToastService } from 'src/app/layout/toast/toast.service';
import { Impact } from 'src/app/toolbox/isms/models/impact.model';
import { ImpactService } from 'src/app/toolbox/isms/services/impact.service';
import { IsmsValidationService } from 'src/app/toolbox/isms/services/isms-validation.service';
import { ISMSService } from 'src/app/toolbox/isms/services/isms.service';
import { nonZeroValidator, numericOrDecimalValidator, uniqueCalculationBasisValidator } from 'src/app/toolbox/isms/utils/isms-utils';


@Component({
    selector: 'app-impact-modal',
    templateUrl: './impact-modal.component.html',
    styleUrls: ['./impact-modal.component.scss'],
    standalone: false
})
export class ImpactModalComponent implements OnInit {
    @Input() impact?: Impact;                  // If provided => Edit mode
    @Input() existingCalculationBases: number[] = []; // For checking duplicates
    @Input() defaultCalculationBasis: number;


    public form: FormGroup;
    public isSubmitting = false;
    public isEditMode = false;
    public isModalVisible = true;
    private isMatrixValid = true;

    public readonly activeModal = inject(NgbActiveModal);
    private readonly fb = inject(FormBuilder);
    private readonly impactService = inject(ImpactService);
    private readonly toast = inject(ToastService);
    private readonly ismsService = inject(ISMSService);
    private readonly modalService = inject(NgbModal);
    private readonly location = inject(Location);

    ngOnInit(): void {
        this.isEditMode = !!this.impact;
        this.buildForm();
        if (this.isEditMode) {
            this.patchForm();
        }
    }

    /**
     * Build the form:
     * - name: required
     * - description: required
     * - calculation_basis: required, must match pattern (^\d+\.\d{1}$), and be unique
     */
    private buildForm(): void {
        // If in edit mode, store the current numeric float value to allow it
        // if the user doesn't change the field
        const currentBasis = this.isEditMode && this.impact
            ? this.impact.calculation_basis
            : undefined;

        this.form = this.fb.group({
            name: ['', Validators.required],
            description: [''],
            calculation_basis: [
                this.defaultCalculationBasis,
                [
                    Validators.required,
                    numericOrDecimalValidator(),
                    nonZeroValidator(),
                    uniqueCalculationBasisValidator(this.existingCalculationBases, currentBasis)
                ]
            ]
        });
    }

    /**
     * If editing, patch the form with existing data.
     */
    private patchForm(): void {
        if (!this.impact) return;
        // Convert the numeric float to a string with exactly one decimal place
        const basisString = this.impact.calculation_basis;

        this.form.patchValue({
            name: this.impact.name,
            description: this.impact.description,
            calculation_basis: basisString
        });
    }

    /**
     * Submit the form for Add or Edit.
     */
    public onSubmit(): void {
        if (this.form.invalid) {
            this.form.markAllAsTouched(); // Force immediate error display
            return;
        }
        this.isSubmitting = true;

        // Keep the user input as a string
        const formValue = this.form.value;

        const payload: Partial<Impact> = {
            name: formValue.name,
            description: formValue.description,
            calculation_basis: parseFloat(formValue.calculation_basis),
            sort: 0
        };

        if (!this.isEditMode) {
            // ADD
            this.impactService
                .createImpact(payload)
                .pipe(finalize(() => (this.isSubmitting = false)))
                .subscribe({
                    next: () => {
                        this.toast.success('Impact created successfully!');
                        this.activeModal.close('saved');
                    },
                    error: (err) => {
                        this.toast.error(err?.error?.message);
                    }
                });
        } else {
            // EDIT
            const publicId = this.impact?.public_id;
            if (!publicId) {
                this.toast.error('No valid ID found for editing.');
                this.isSubmitting = false;
                return;
            }

            const calculationBasisChanged =
                this.impact?.calculation_basis !== payload.calculation_basis;

            this.impactService
                .updateImpact(publicId, payload)
                .pipe(finalize(() => (this.isSubmitting = false)))
                .subscribe({
                    next: () => {
                        this.toast.success('Impact updated successfully!');
                        this.activeModal.close('saved');

                        // If calculation_basis was changed, show the warning dialog
                        if (calculationBasisChanged) {
                            this.ismsService.getIsmsValidationStatus().subscribe({
                                next: (status) => {
                                    if (status?.risk_matrix) {
                                        const modalRef = this.modalService.open(CoreWarningModalComponent, { centered: true });
                                        modalRef.componentInstance.title = 'Risk Matrix Needs Review';
                                        modalRef.componentInstance.message = 'You have modified the calculation basis for Impact. Please review the Risk Matrix accordingly to reflect these changes.';
                                        modalRef.componentInstance.cancelLabel = 'Continue';

                                        // Listen to modal result
                                        return modalRef.result.then(
                                            () => false, // when confirmed
                                            () => {
                                                return false;
                                            }
                                        );
                                    }
                                }
                            })
                        }
                    },
                    error: (err) => {
                        this.toast.error(err?.error?.message);
                    }
                });
        }
    }

    public onCancel(): void {
        this.activeModal.dismiss('cancel');
    }
}
