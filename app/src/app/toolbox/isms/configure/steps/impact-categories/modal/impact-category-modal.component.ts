import { Component, inject, Input, OnInit } from '@angular/core';
import {
  FormBuilder,
  FormGroup,
  FormArray,
  Validators
} from '@angular/forms';
import { NgbActiveModal } from '@ng-bootstrap/ng-bootstrap';
import { finalize } from 'rxjs/operators';

import { ToastService } from 'src/app/layout/toast/toast.service';
import { ImpactCategory } from 'src/app/toolbox/isms/models/impact-category.model';
import { ImpactCategoryService } from 'src/app/toolbox/isms/services/impact-category.service';
import { Impact } from 'src/app/toolbox/isms/models/impact.model';
import { ImpactService } from 'src/app/toolbox/isms/services/impact.service';
import { Sort, SortDirection } from 'src/app/layout/table/table.types';

@Component({
    selector: 'app-impact-category-modal',
    templateUrl: './impact-category-modal.component.html',
    styleUrls: ['./impact-category-modal.component.scss'],
    standalone: false
})
export class ImpactCategoryModalComponent implements OnInit {
  /**
   * If provided, we're in "Edit" or "Copy" mode.
   * In copy mode the data is prefilled but the public_id will be omitted.
   */
  @Input() impactCategory?: ImpactCategory;
  /**
   * When true, the modal is opened in read-only mode.
   */
  @Input() isViewMode = false;
  /**
   * When true, the modal is in "Copy As New" mode.
   */
  @Input() isCopyMode = false;


  @Input() sort?: number;

  public form: FormGroup;
  public isSubmitting = false;
  public isEditMode = false; // true if editing (impactCategory provided and not in copy mode)

  // All impacts fetched from API to build a row for each impact
  public allImpacts: Impact[] = [];

  public readonly activeModal = inject(NgbActiveModal);
  private readonly fb = inject(FormBuilder);
  private readonly impactCategoryService = inject(ImpactCategoryService);
  private readonly impactService = inject(ImpactService);
  private readonly toast = inject(ToastService);


  ngOnInit(): void {
    // Determine mode: if impactCategory is provided and not copy mode, we're in edit mode.
    this.isEditMode = !!this.impactCategory && !this.isCopyMode;
    this.buildForm();
    this.fetchAllImpacts();
  }


  /**
   * Build the main form: category name and impact_descriptions (as FormArray).
   */
  private buildForm(): void {
    this.form = this.fb.group({
      name: ['', Validators.required],
      impact_descriptions: this.fb.array([]),
      sort: this.sort
    });
  }


  /**
   * Fetch all Impacts from the API, then build (or patch) the impact_descriptions FormArray.
   */
  private fetchAllImpacts(): void {
    const sort: Sort = { name: 'calculation_basis', order: SortDirection.DESCENDING } as Sort;
    this.impactService
      .getImpacts({ filter: '', limit: 0, page: 1, sort: sort.name, order: sort.order })
      .subscribe({
        next: (data) => {
          this.allImpacts = data.results;
          this.buildOrPatchDescriptions();
        },
        error: (err) => {
          this.toast.error(err?.error?.message);
        }
      });
  }


  /**
   * Build or patch the impact_descriptions FormArray.
   * For each Impact from the backend, create a row with:
   * - impact_id (hidden)
   * - impact_name (read-only display)
   * - value (required description input)
   * In edit (or copy) mode, if an existing description is found for an impact, prefill it.
   */
  private buildOrPatchDescriptions(): void {
    const descArray = this.form.get('impact_descriptions') as FormArray;
    descArray.clear();

    // If editing (or copying), patch the category name
    if (this.isEditMode && this.impactCategory) {
      this.form.patchValue({ name: this.impactCategory.name });
    }

    // Build a map for existing descriptions (if editing or copy)
    const existingMap = new Map<number, string>();
    if ((this.isEditMode || this.isCopyMode) && this.impactCategory) {
      for (const desc of this.impactCategory.impact_descriptions || []) {
        existingMap.set(desc.impact_id, desc.value);
      }
    }

    // For each Impact fetched from API, add a row.
    this.allImpacts.forEach((imp) => {
      const existingValue = existingMap.get(imp.public_id!) || '';
      descArray.push(
        this.fb.group({
          impact_id: [imp.public_id, Validators.required],
          impact_name: [imp.name], // for display only
          value: [existingValue]
        })
      );
    });

    // If view mode, disable the form.
    if (this.isViewMode) {
      this.form.disable();
    }
  }


  /**
   * Getter for the impact_descriptions FormArray.
   */
  get impactDescriptions(): FormArray {
    return this.form.get('impact_descriptions') as FormArray;
  }


  /**
   * onSubmit: validate the form and send the payload.
   * If in edit mode (and not copy mode), include public_id in the payload.
   * In add or copy mode, do not send public_id.
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

    // Build the final impact_descriptions array
    const finalDescs = formValue.impact_descriptions.map((d: any) => ({
      impact_id: d.impact_id,
      value: d.value
    }));

    // Build payload.
    // In edit mode (and not copy mode), include public_id.
    const payload: Partial<ImpactCategory> = {
      name: formValue.name,
      impact_descriptions: finalDescs,
      sort: this.sort
    };

    if (this.isEditMode) {
      // In edit mode, include public_id from impactCategory.
      payload.public_id = this.impactCategory?.public_id;
    }

    if (!this.isEditMode && !this.isCopyMode) {
      // Add mode.
      this.impactCategoryService.createImpactCategory(payload)
        .pipe(finalize(() => (this.isSubmitting = false)))
        .subscribe({
          next: () => {
            this.toast.success('Impact Category created successfully!');
            this.activeModal.close('saved');
          },
          error: (err) => {
            this.toast.error(err?.error?.message);
          }
        });
    } else if (this.isEditMode && !this.isCopyMode) {
      // Edit mode: payload includes public_id.
      const public_id = this.impactCategory?.public_id;
      if (!public_id) {
        this.toast.error('No valid ID found for editing.');
        this.isSubmitting = false;
        return;
      }
      this.impactCategoryService.updateImpactCategory(public_id, payload)
        .pipe(finalize(() => (this.isSubmitting = false)))
        .subscribe({
          next: () => {
            this.toast.success('Impact Category updated successfully!');
            this.activeModal.close('saved');
          },
          error: (err) => {
            this.toast.error(err?.error?.message);
          }
        });
    } else {
      // Copy mode: treat as add, do not send public_id.

      this.impactCategoryService.createImpactCategory(payload)
        .pipe(finalize(() => (this.isSubmitting = false)))
        .subscribe({
          next: () => {
            this.toast.success('Impact Category copied successfully!');
            this.activeModal.close('saved');
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
