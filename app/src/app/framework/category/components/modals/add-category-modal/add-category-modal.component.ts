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
* along with this program. If not, see <https://www.gnu.org/licenses/>.
*/
import { Component, OnInit } from '@angular/core';
import { UntypedFormControl, UntypedFormGroup, Validators } from '@angular/forms';

import { NgbActiveModal } from '@ng-bootstrap/ng-bootstrap';

import { CategoryService, checkCategoryExistsValidator } from '../../../../services/category.service';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'cmdb-add-category-modal',
    templateUrl: './add-category-modal.component.html',
    styleUrls: ['./add-category-modal.component.scss'],
    standalone: false
})
export class AddCategoryModalComponent implements OnInit {

  public catAddForm: UntypedFormGroup;


    constructor(public activeModal: NgbActiveModal, private categoryService: CategoryService) {
        this.catAddForm = new UntypedFormGroup({
            name: new UntypedFormControl('', Validators.required),
            label: new UntypedFormControl('')
        });
    }


    public ngOnInit(): void {
        this.name.setAsyncValidators(checkCategoryExistsValidator(this.categoryService));
    }


    public get name(): UntypedFormControl {
        return this.catAddForm.get('name') as UntypedFormControl;
    }


    public get label(): UntypedFormControl {
        return this.catAddForm.get('label') as UntypedFormControl;
    }
}
