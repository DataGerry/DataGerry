/*
* DATAGERRY - OpenSource Enterprise CMDB
* Copyright (C) 2025 becon GmbH
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

import { Component, Input, OnInit } from '@angular/core';
import { FormBuilder, FormGroup, Validators } from '@angular/forms';
import { NgbActiveModal, NgbModal } from '@ng-bootstrap/ng-bootstrap';
import { finalize } from 'rxjs/operators';
import { CoreWarningModalComponent } from 'src/app/core/components/dialog/core-warning-modal/core-warning-modal.component';

import { ToastService } from 'src/app/layout/toast/toast.service';
import { Likelihood } from 'src/app/toolbox/isms/models/likelihood.model';
import { ISMSService } from 'src/app/toolbox/isms/services/isms.service';
import { LikelihoodService } from 'src/app/toolbox/isms/services/likelihood.service';
import { nonZeroValidator, numericOrDecimalValidator, uniqueCalculationBasisValidator } from 'src/app/toolbox/isms/utils/isms-utils';

@Component({
    selector: 'app-likelihood-modal',
    templateUrl: './likelihood-modal.component.html',
    styleUrls: ['./likelihood-modal.component.scss'],
    standalone: false
})
export class LikelihoodModalComponent implements OnInit {
  @Input() likelihood?: Likelihood; // Provided => Edit mode
  @Input() existingCalculationBases: number[] = []; // For duplicate checking
  @Input() defaultCalculationBasis: number;

  public form: FormGroup;
  public isSubmitting = false;
  public isEditMode = false;

  constructor(
    public activeModal: NgbActiveModal,
    private fb: FormBuilder,
    private likelihoodService: LikelihoodService,
    private toast: ToastService,
    private ismsService: ISMSService,
    private modalService: NgbModal,
    
  ) { }

  ngOnInit(): void {
    this.isEditMode = !!this.likelihood;
    this.buildForm();
    if (this.isEditMode) {
      this.patchForm();
    }

  }

  /**
   * Build the form.
   * - Name: required
   * - Description: required
   * - Calculation Basis: required
   */
  private buildForm(): void {
    const currentBasis = this.isEditMode && this.likelihood ? this.likelihood.calculation_basis : undefined;
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
   * Patch the form with existing data in edit mode.
   */
  private patchForm(): void {
    if (!this.likelihood) return;
    const basisString = this.likelihood.calculation_basis;
    this.form.patchValue({
      name: this.likelihood.name,
      description: this.likelihood.description,
      calculation_basis: basisString
    });
  }


  /**
   * Handle form submission for Add or Edit.
   */
  public onSubmit(): void {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }
    this.isSubmitting = true;
    const formValue = this.form.value;
    const payload: Partial<Likelihood> = {
      name: formValue.name,
      description: formValue.description,
      calculation_basis: parseFloat(formValue.calculation_basis),
      sort: 0
    };

    if (!this.isEditMode) {
      // Add mode
      this.likelihoodService.createLikelihood(payload)
        .pipe(finalize(() => (this.isSubmitting = false)))
        .subscribe({
          next: () => {
            this.toast.success('Likelihood created successfully!');
            this.activeModal.close('saved');
          },
          error: (err) => {
            this.toast.error(err?.error?.message);
          }
        });
    } else {
      // Edit mode
      const publicId = this.likelihood?.public_id;
      if (!publicId) {
        this.toast.error('No valid ID found for editing.');
        this.isSubmitting = false;
        return;
      }
      this.likelihoodService.updateLikelihood(publicId, payload)
        .pipe(finalize(() => (this.isSubmitting = false)))
        .subscribe({
          next: () => {
            this.toast.success('Likelihood updated successfully!');
            this.activeModal.close('saved');

            this.ismsService.getIsmsValidationStatus().subscribe({
              next: (status) => {
                if (status?.risk_matrix) {
                  const modalRef = this.modalService.open(CoreWarningModalComponent, { centered: true });
                  modalRef.componentInstance.title = 'Risk Matrix Needs Review';
                  modalRef.componentInstance.message = 'You have modified the calculation basis for likelihood. Please review the Risk Matrix accordingly to reflect these changes.';
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
