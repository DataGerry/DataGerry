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
    templateUrl: './delete-category-modal.component.html',
    styleUrls: ['./delete-category-modal.component.scss'],
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
