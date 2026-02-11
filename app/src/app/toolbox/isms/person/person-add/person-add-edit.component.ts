/*
* DATAGERRY - OpenSource Enterprise CMDB
* Copyright (C) 2026 becon GmbH
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
import { Component, OnInit } from '@angular/core';
import { Router } from '@angular/router';
import { FormBuilder, FormGroup, Validators } from '@angular/forms';
import { finalize } from 'rxjs/operators';

import { LoaderService } from 'src/app/core/services/loader.service';
import { ToastService } from 'src/app/layout/toast/toast.service';

import { PersonService } from '../../services/person.service';
import { PersonGroupService } from '../../services/person-group.service';

import { CmdbPerson } from '../../models/person.model';
import { CmdbPersonGroup } from '../../models/person-group.model';

import { CollectionParameters } from 'src/app/services/models/api-parameter';
import { SortDirection } from 'src/app/layout/table/table.types';

@Component({
    selector: 'app-person-add-edit',
    templateUrl: './person-add-edit.component.html',
    styleUrls: ['./person-add-edit.component.scss'],
    standalone: false
})
export class PersonAddEditComponent implements OnInit {
  public isEditMode = false;
  public isViewMode = false;
  public isLoading$ = this.loaderService.isLoading$;

  // Reactive Form for Person
  public personForm: FormGroup;

  // Original person data (if editing)
  public personData: CmdbPerson = {
    first_name: '',
    last_name: '',
    display_name: '',
    phone_number: '',
    email: '',
    groups: []
  };

  // Basic email regex
  private readonly emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

  // All PersonGroups for the multi-select
  public allGroups: CmdbPersonGroup[] = [];

  constructor(
    private router: Router,
    private fb: FormBuilder,
    private loaderService: LoaderService,
    private toast: ToastService,
    private personService: PersonService,
    private personGroupService: PersonGroupService
  ) {
    const navState = this.router.getCurrentNavigation()?.extras?.state;
    if (navState?.['person']) {
      this.isEditMode = true;
      this.personData = navState['person'];
    }
    if (navState?.['mode'] === 'view') {
      this.isViewMode = true;
    }

    // Initialize the form
    this.personForm = this.fb.group({
      public_id: [this.personData.public_id || null],
      first_name: [this.personData.first_name, [Validators.required]],
      last_name: [this.personData.last_name, [Validators.required]],
      display_name: [this.personData.display_name || ''],
      phone_number: [
        this.personData.phone_number || '',
        [
          Validators.pattern(
            /^\+?[1-9]\d{1,14}$/
          ) 
        ]
      ], email: [
        this.personData.email,
        [Validators.pattern(this.emailRegex)]
      ],
      groups: [this.personData.groups || []]
    });
  }

  ngOnInit(): void {
    // If read-only, disable the form
    if (this.isViewMode) {
      this.personForm.disable();
    }
    // Load group references
    this.loadGroups();
    // Update display_name in case first_name / last_name changed

    this.personForm.get('first_name')?.valueChanges.subscribe(() => this.updateDisplayName());
    this.personForm.get('last_name')?.valueChanges.subscribe(() => this.updateDisplayName());
  }


  /**
   * Load PersonGroup references
   * @returns void
   */
  private loadGroups(): void {
    if (this.isViewMode && this.personData.groups?.length) {
      // Only the groups that match
      const filterObj = { public_id: { '$in': this.personData.groups } };
      const params: CollectionParameters = {
        filter: JSON.stringify(filterObj),
        page: 1,
        limit: 0,
        sort: 'public_id',
        order: SortDirection.ASCENDING
      };
      this.loaderService.show();
      this.personGroupService.getPersonGroups(params)
        .pipe(finalize(() => this.loaderService.hide()))
        .subscribe({
          next: (resp) => {
            this.allGroups = resp.results;
          },
          error: (err) => {
            this.toast.error(err?.error?.message);
          }
        });
    } else {
      // Normal create/edit => load all
      const params: CollectionParameters = {
        filter: '',
        page: 1,
        limit: 0,
        sort: 'public_id',
        order: SortDirection.ASCENDING
      };
      this.loaderService.show();
      this.personGroupService.getPersonGroups(params)
        .pipe(finalize(() => this.loaderService.hide()))
        .subscribe({
          next: (resp) => {
            this.allGroups = resp.results;
          },
          error: (err) => {
            this.toast.error(err?.error?.message);
          }
        });
    }
  }

  /**
   * Update display_name based on first_name and last_name
   * @returns void
 */
  private updateDisplayName(): void {
    const fn = this.personForm.get('first_name')?.value || '';
    const ln = this.personForm.get('last_name')?.value || '';
    const combined = (fn + ' ' + ln).trim();
    this.personForm.patchValue({ display_name: combined });
  }


  /**
    * Handles Save: create or update the Person
    * @returns void
    */
  public onSave(): void {
    if (this.isViewMode) {
      // do nothing or just navigate
      return;
    }

    if (this.personForm.invalid) {
      this.personForm.markAllAsTouched();
      return;
    }

    const formValue = this.personForm.value as CmdbPerson;

    if (this.isEditMode && formValue.public_id) {
      this.updatePerson(formValue.public_id, formValue);
    } else {
      delete formValue.public_id; // Remove public_id for creation
      this.createPerson(formValue);
    }
  }


  /**
   * Create a new person via service
   * @param newData: new person data
   * @returns void
   */
  private createPerson(newData: CmdbPerson): void {
    this.loaderService.show();
    this.personService.createPerson(newData)
      .pipe(finalize(() => this.loaderService.hide()))
      .subscribe({
        next: () => {
          this.toast.success('Person created successfully');
          this.router.navigate(['/framework/persons']);
        },
        error: (err) => {
          this.toast.error(err?.error?.message);
        }
      });
  }


  /**
   * Update an existing person via service
   * @param id: public_id of the person to update
   * @param updated: updated person data
   * @returns void
   */
  private updatePerson(id: number, updated: CmdbPerson): void {
    this.loaderService.show();
    this.personService.updatePerson(id, updated)
      .pipe(finalize(() => this.loaderService.hide()))
      .subscribe({
        next: () => {
          this.toast.success('Person updated successfully');
          this.router.navigate(['/framework/persons']);
        },
        error: (err) => {
          this.toast.error(err?.error?.message);
        }
      });
  }


  /**
   * Cancel and go back to the list
   * @returns void
   */
  public onCancel(): void {
    this.router.navigate(['/framework/persons']);
  }


  /**
   * For error messages below fields
   * @params controlName: name of the form control
   * @params errorName: name of the error to check
   * @returns true if the control has the error and is dirty or touched
   */
  public hasError(controlName: string, errorName: string): boolean {
    const control = this.personForm.get(controlName);
    return !!(
      control &&
      control.hasError(errorName) &&
      (control.dirty || control.touched)
    );
  }

}
