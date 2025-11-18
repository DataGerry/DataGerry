import { Component, Input, OnInit } from '@angular/core';
import { FormBuilder, FormGroup, Validators } from '@angular/forms';
import { NgbActiveModal } from '@ng-bootstrap/ng-bootstrap';
import { finalize } from 'rxjs/operators';

import { ToastService } from 'src/app/layout/toast/toast.service';
import { RiskClass } from 'src/app/toolbox/isms/models/risk-class.model';
import { RiskClassService } from 'src/app/toolbox/isms/services/risk-class.service';

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

  constructor(
    public activeModal: NgbActiveModal,
    private fb: FormBuilder,
    private riskClassService: RiskClassService,
    private toast: ToastService
  ) {}

  
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
      color: ['#ff0000', Validators.required],  // default color
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
