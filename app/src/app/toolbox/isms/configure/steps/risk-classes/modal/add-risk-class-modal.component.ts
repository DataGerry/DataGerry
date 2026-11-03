import { Component, inject, Input, OnInit } from '@angular/core';
import { FormBuilder, FormGroup, Validators } from '@angular/forms';
import { NgbActiveModal } from '@ng-bootstrap/ng-bootstrap';
import { finalize } from 'rxjs/operators';

import { ToastService } from 'src/app/layout/toast/toast.service';
import { RiskClass } from 'src/app/toolbox/isms/models/risk-class.model';
import { RiskClassService } from 'src/app/toolbox/isms/services/risk-class.service';
import { hexColorErrorMessage, hexColorValidator } from 'src/app/core/utils/hex-color-validator';

@Component({
    selector: 'app-risk-class-modal',
    templateUrl: './risk-class-modal.component.html',
    styleUrls: ['./risk-class-modal.component.scss'],
    standalone: false
})
export class RiskClassModalComponent implements OnInit {
  @Input() riskClass?: RiskClass; // If provided => "Edit" mode
  @Input() sort?: number
  public form: FormGroup;
  public isSubmitting = false;
  public isEditMode = false;

  public readonly activeModal = inject(NgbActiveModal);
  private readonly fb = inject(FormBuilder);
  private readonly riskClassService = inject(RiskClassService);
  private readonly toast = inject(ToastService);

  
  ngOnInit(): void {
    this.isEditMode = !!this.riskClass; // true if we have an existing item
    this.buildForm();
    if (this.isEditMode) {
      this.patchForm();
    }
  }

  /**
   * Initialize the form with default or empty fields.
   */
  private buildForm(): void {
    this.form = this.fb.group({
      name: ['', Validators.required],
      color: ['#ff0000', [Validators.required, hexColorValidator()]],  // default color
      description: [''],
      sort: this.sort
    });
  }


  /**
   * If editing, patch the form with existing data.
   */
  private patchForm(): void {
    if (!this.riskClass) return;
    this.form.patchValue({
      name: this.riskClass.name,
      color: this.riskClass.color,
      description: this.riskClass.description,
      sort: this.riskClass.sort
    });

    // The API does not validate colours, so show a bad stored one right away.
    if (this.form.get('color')?.invalid) {
      this.form.get('color')?.markAsTouched();
    }
  }


  public get colorError(): string {
    return hexColorErrorMessage(this.form.get('color'));
  }


  /**
   * Handle form submission for Add or Edit.
   */
  public onSubmit(): void {
    if (this.form.invalid) {
      return;
    }
    this.isSubmitting = true;

    const formData = this.form.value as RiskClass;
    if (!this.isEditMode) {
      // CREATE
      this.riskClassService.createRiskClass(formData)
        .pipe(finalize(() => (this.isSubmitting = false)))
        .subscribe({
          next: () => {
            this.toast.success('Risk Class created successfully!');
            this.activeModal.close('saved');
          },
          error: (err) => {
            this.toast.error(err?.error?.message);
          }
        });
    } else {
      // UPDATE
      const publicId = this.riskClass?.public_id;
      if (!publicId) {
        this.toast.error('No valid ID found for editing.');
        this.isSubmitting = false;
        return;
      }
      this.riskClassService.updateRiskClass(publicId, formData)
        .pipe(finalize(() => (this.isSubmitting = false)))
        .subscribe({
          next: () => {
            this.toast.success('Risk Class updated successfully!');
            this.activeModal.close('saved');
          },
          error: (err) => {
            this.toast.error(err?.error?.message);
          }
        });
    }
  }


  /**
   * Dismiss the modal without saving.
   */
  public onCancel(): void {
    this.activeModal.dismiss('cancel');
  }
}
