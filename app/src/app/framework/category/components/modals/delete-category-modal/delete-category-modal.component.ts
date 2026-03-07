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

* You should have received a copy of the GNU Affero General Public License
* along with this program. If not, see <https://www.gnu.org/licenses/>.
*/

import {Component, Input, OnDestroy} from '@angular/core';
import {NgbActiveModal, NgbModalRef} from '@ng-bootstrap/ng-bootstrap';
import { CmdbCategory } from '../../../../models/cmdb-category';
import { AbstractControl, UntypedFormControl, UntypedFormGroup, ValidatorFn, Validators } from '@angular/forms';

@Component({
    selector: 'cmdb-category-delete',
    template: `
    <div class="modal-header bg-primary text-white">
      <h4 class="modal-title" id="modal-title">Delete Category:</h4>
      <button type="button" class="btn-close btn-close-white" aria-label="Close" (click)="modal.dismiss('cancel')"></button>
    </div>
    <div class="modal-body">
      <strong>Do you want to <b>delete</b> the Category <b>"{{ category.name }}"</b>?</strong>
      <p>
        All types inside this category will be unassigned.
        <span class="text-danger">This operation cannot be undone!</span>
      </p>
      <form id="deleteCategoryModalForm" [formGroup]="deleteCategoryModalForm" class="needs-validation" novalidate
            autocomplete="off">
        <div class="form-group">
          <label for="categoryNameInput">Type in the name: {{ category.name }} <span class="required">*</span></label>
          <input type="text" formControlName="name" class="form-control"
                 [ngClass]="{ 'is-valid': name.valid && (name.dirty || name.touched),
                 'is-invalid': name.invalid && (name.dirty || name.touched)}"
                 id="categoryNameInput" required>
          <small id="categoryNameInputHelp" class="form-text text-muted">Type in the name of the category to confirm the
            deletion.</small>
          <div *ngIf="name.invalid && (name.dirty || name.touched)"
               class="invalid-feedback">
            <div class="text-end" *ngIf="name.errors.required">
              Name is required
            </div>
            <div class="text-end" *ngIf="name.errors.notequal">
              Your answer is not equal!
            </div>
          </div>
          <div class="clearfix"></div>
        </div>
      </form>
    </div>
    <div class="modal-footer">
      <button type="button" class="btn btn-outline-dark" (click)="modal.dismiss('cancel')">Close</button>
      <button type="button" class="btn btn-danger" [disabled]="deleteCategoryModalForm.invalid"
              (click)="modal.close('delete')">Delete
      </button>
    </div>
  `,
    standalone: false
})
export class DeleteCategoryModalComponent implements OnDestroy {

  constructor(public modal: NgbActiveModal) {
    this.deleteCategoryModalForm = new UntypedFormGroup({
      name: new UntypedFormControl('', [Validators.required, this.equalName()]),
    });
  }

  public get name(): UntypedFormControl {
    return this.deleteCategoryModalForm.get('name') as UntypedFormControl;
  }

  @Input() public category: CmdbCategory;
  public deleteCategoryModalForm: UntypedFormGroup;
  private modalRef: NgbModalRef;

  public ngOnDestroy(): void {
    if (this.modalRef) {
      this.modalRef.close();
    }
  }

  public equalName(): ValidatorFn {
    return (control: AbstractControl): { [key: string]: boolean } | null => {
      if (this.category) {
        if (control.value !== this.category.name) {
          return { notequal: true };
        } else {
          return null;
        }
      }

    };
  }

}
