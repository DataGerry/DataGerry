import { Component, OnInit } from '@angular/core';
import { Router } from '@angular/router';
import { FormBuilder, FormGroup, Validators } from '@angular/forms';
import { finalize } from 'rxjs/operators';

import { LoaderService } from 'src/app/core/services/loader.service';
import { ToastService } from 'src/app/layout/toast/toast.service';

import { PersonGroupService } from 'src/app/toolbox/isms/services/person-group.service';
import { PersonService } from 'src/app/toolbox/isms/services/person.service';

import { CmdbPersonGroup } from 'src/app/toolbox/isms/models/person-group.model';
import { CmdbPerson } from 'src/app/toolbox/isms/models/person.model';

import { CollectionParameters } from 'src/app/services/models/api-parameter';
import { SortDirection } from 'src/app/layout/table/table.types';

@Component({
    selector: 'app-person-group-add-edit',
    templateUrl: './person-group-add-edit.component.html',
    styleUrls: ['./person-group-add-edit.component.scss'],
    standalone: false
})
export class PersonGroupAddEditComponent implements OnInit {
  public isEditMode = false;
  public isViewMode = false; // If true, read-only
  public isLoading$ = this.loaderService.isLoading$; 

  // FormGroup for PersonGroup
  public personGroupForm: FormGroup;

  // We store the original data if needed
  public personGroupData: CmdbPersonGroup = {
    name: '',
    email: '',
    group_members: []
  };

  // A basic email regex
  private readonly emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

  // We store all Person references (for group_members multi-select)
  public allPersons: CmdbPerson[] = [];

  constructor(
    private router: Router,
    private fb: FormBuilder,
    private loaderService: LoaderService,
    private toast: ToastService,
    private personGroupService: PersonGroupService,
    private personService: PersonService
  ) {
    // Check if the state was passed for edit or view
    const navState = this.router.getCurrentNavigation()?.extras?.state;
    if (navState?.['personGroup']) {
      this.isEditMode = true;
      this.personGroupData = navState['personGroup'];
    }
    if (navState?.['mode'] === 'view') {
      this.isViewMode = true;
    }

    // Initialize FormGroup
    this.personGroupForm = this.fb.group({
      public_id: [this.personGroupData.public_id || null],
      name: [this.personGroupData.name, [Validators.required]],
      email: [
        this.personGroupData.email,
        [Validators.pattern(this.emailRegex)]
      ],
      group_members: [this.personGroupData.group_members || []]
    });
  }

  ngOnInit(): void {
    // Load either filtered members if in viewMode, or all if edit/create
    this.loadAllPersons();
    // If we are in read-only (view) mode, just disable the form
    if (this.isViewMode) {
      this.personGroupForm.disable();
    }
  }

  /**
   * Load all persons or filter them based on the group_members in view mode
   * @returns void
   */
  private loadAllPersons(): void {
    if (this.isViewMode && this.personGroupData.group_members?.length) {
      // Build filter
      const filterObj = { public_id: { '$in': this.personGroupData.group_members } };
      const params: CollectionParameters = {
        filter: JSON.stringify(filterObj),
        page: 1,
        limit: 0,
        sort: 'public_id',
        order: SortDirection.ASCENDING
      };
      this.loaderService.show();
      this.personService.getPersons(params)
        .pipe(finalize(() => this.loaderService.hide()))
        .subscribe({
          next: (resp) => {
            this.allPersons = resp.results;
          },
          error: (err) => {
            this.toast.error(err?.error?.message);
          }
        });
    } else if (!this.isViewMode) {
      // Normal create/edit => load all
      const params: CollectionParameters = {
        filter: '',
        page: 1,
        limit: 0,
        sort: 'public_id',
        order: SortDirection.ASCENDING
      };
      this.loaderService.show();
      this.personService.getPersons(params)
        .pipe(finalize(() => this.loaderService.hide()))
        .subscribe({
          next: (resp) => {
            this.allPersons = resp.results;
          },
          error: (err) => {
            this.toast.error(err?.error?.message);
          }
        });
    }
  }


  /**
   * Update display_name when first_name or last_name changes
   * @returns void
   */
  public onSave(): void {
    if (this.isViewMode) {
      // If purely view mode, do nothing (or navigate away)
      return;
    }

    // If invalid, mark all as touched so error messages appear
    if (this.personGroupForm.invalid) {
      this.personGroupForm.markAllAsTouched();
      return;
    }

    // Merge form value
    const formValue = this.personGroupForm.value as CmdbPersonGroup;

    if (this.isEditMode && formValue.public_id) {
      // Update
      this.updatePersonGroup(formValue.public_id, formValue);
    } else {
      // Create
      delete formValue.public_id;
      this.createPersonGroup(formValue);
    }
  }


  /**
   * Create a new person group via service
   * @param newData: new person group data
   * @returns void
   */
  private createPersonGroup(newData: CmdbPersonGroup): void {
    this.loaderService.show();
    this.personGroupService.createPersonGroup(newData)
      .pipe(finalize(() => this.loaderService.hide()))
      .subscribe({
        next: () => {
          this.toast.success('Person Group created successfully');
          this.router.navigate(['/framework/person-groups']);
        },
        error: (err) => {
          this.toast.error(err?.error?.message);
        }
      });
  }

  /**
   * Update an existing person group via service
   * @param id: public_id of the person group to update
   * @param updated: updated person group data
   * @returns void
   */
  private updatePersonGroup(id: number, updated: CmdbPersonGroup): void {
    this.loaderService.show();
    this.personGroupService.updatePersonGroup(id, updated)
      .pipe(finalize(() => this.loaderService.hide()))
      .subscribe({
        next: () => {
          this.toast.success('Person Group updated successfully');
          this.router.navigate(['/framework/person-groups']);
        },
        error: (err) => {
          this.toast.error(err?.error?.message);
        }
      });
  }


  /**
   * Called when the user clicks "Cancel"
   * @returns void
   */
  public onCancel(): void {
    this.router.navigate(['/framework/person-groups']);
  }


  /**
   * Helper to show an error in the template
   * @param controlName: name of the form control
   * @param errorName: name of the error to check 
   * @return true if the control has the error and is dirty or touched
   */
  public hasError(controlName: string, errorName: string): boolean {
    const control = this.personGroupForm.get(controlName);
    return !!(
      control &&
      control.hasError(errorName) &&
      (control.dirty || control.touched)
    );
  }
}
