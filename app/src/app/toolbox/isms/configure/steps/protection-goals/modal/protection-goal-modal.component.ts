import { Component, inject, Input, OnInit } from '@angular/core';
import { FormBuilder, FormGroup, Validators } from '@angular/forms';
import { NgbActiveModal } from '@ng-bootstrap/ng-bootstrap';
import { finalize } from 'rxjs/operators';

import { ToastService } from 'src/app/layout/toast/toast.service';
import { ProtectionGoal } from 'src/app/toolbox/isms/models/protection-goal.model';
import { ProtectionGoalService } from 'src/app/toolbox/isms/services/protection-goal.service';

@Component({
    selector: 'app-protection-goal-modal',
    templateUrl: './protection-goal-modal.component.html',
    styleUrls: ['./protection-goal-modal.component.scss'],
    standalone: false
})
export class ProtectionGoalModalComponent implements OnInit {
  @Input() protectionGoal?: ProtectionGoal; // If provided => Edit mode.
  @Input() protectionGoals?: ProtectionGoal[];
  @Input() isViewMode = false;
  @Input() isCopyMode = false;

  public form: FormGroup;
  public isSubmitting = false;
  public isEditMode = false;
  public isDuplicateName = false;

  public readonly activeModal = inject(NgbActiveModal);
  private readonly fb = inject(FormBuilder);
  private readonly protectionGoalService = inject(ProtectionGoalService);
  private readonly toast = inject(ToastService);

  ngOnInit(): void {
    // Determine mode: edit if protectionGoal provided and not copy mode.
    this.isEditMode = !!this.protectionGoal && !this.isCopyMode;
    this.buildForm();
    if (this.protectionGoal) {
      this.patchForm();
    }
    if (this.isViewMode) {
      this.form.disable();
    }
  }


  /**
   * Initialize form fields.
   */
  private buildForm(): void {
    this.form = this.fb.group({
      name: ['', Validators.required]
    });
  }


  /**
   * Patch form with protection goal data in edit/copy/view mode.
   */
  private patchForm(): void {
    if (!this.protectionGoal) return;
    this.form.patchValue({
      name: this.protectionGoal.name
    });
  }


  /**
   * Check if the entered name already exists in the ProtectionGoals list.
   */
  public checkDuplicateName(): void {
    const enteredName = this.form.get('name')?.value?.trim().toLowerCase();
    this.isDuplicateName = this.protectionGoals?.some(
      (goal) => goal.name.trim().toLowerCase() === enteredName
    ) || false;
    if (this.isDuplicateName) {
      this.form.get('name')?.setErrors({ duplicate: true });
    } else {
      this.form.get('name')?.setErrors(null);
    }          
  }


  /**
   * Submit form data (create or update).
   */
  public onSubmit(): void {
    if (this.isViewMode) {
      return;
    }
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }
    this.isSubmitting = true;
    const formValue = this.form.value;
    const payload: Partial<ProtectionGoal> = {
      name: formValue.name,
      predefined: false,
    };

    if (this.isEditMode) {
      // Edit mode: include public_id.
      payload.public_id = this.protectionGoal?.public_id;
      if (!payload.public_id) {
        this.toast.error('No valid ID found for editing.');
        this.isSubmitting = false;
        return;
      }
      this.protectionGoalService.updateProtectionGoal(payload.public_id, payload)
        .pipe(finalize(() => (this.isSubmitting = false)))
        .subscribe({
          next: () => {
            this.toast.success('Protection Goal updated successfully!');
            this.activeModal.close('saved');
          },
          error: (err) => {
            this.toast.error(err?.error?.message);
          }
        });
    } else {
      // Add or Copy mode: do not send public_id.
      this.protectionGoalService.createProtectionGoal(payload)
        .pipe(finalize(() => (this.isSubmitting = false)))
        .subscribe({
          next: () => {
            const msg = this.isCopyMode ? 'Protection Goal copied successfully!' : 'Protection Goal created successfully!';
            this.toast.success(msg);
            this.activeModal.close('saved');
          },
          error: (err) => {
            this.toast.error(err?.error?.message);
          }
        });
    }
  }


  /**
   * Close modal without saving.
   */
  public onCancel(): void {
    this.activeModal.dismiss('cancel');
  }
}
