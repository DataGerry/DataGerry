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

import { Component, inject } from '@angular/core';
import { FormGroup, FormControl, ValidatorFn } from '@angular/forms';

import { NgbActiveModal } from '@ng-bootstrap/ng-bootstrap';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'cmdb-branch-info-modal',
    templateUrl: './branch-info-modal.component.html',
    styleUrls: ['./branch-info-modal.component.scss'],
    standalone: false
})
  export class BranchInfoModalComponent {
    
    public readonly activeModal = inject(NgbActiveModal);


    branchForm: FormGroup = new FormGroup({
      'telecommunications-branch': new FormControl(false),
      'helpdesk-branch': new FormControl(false),
      'service-provider-branch': new FormControl(false),
      'healthcare-branch': new FormControl(false),
    },
      this.oneCheckedRequired()
    );


    /**
     * Validator for which checks if at least one checkbox is selected
     * 
     * @returns Error or null
     */
    public oneCheckedRequired(): ValidatorFn {
      return function validate(formGroup: FormGroup) {
        let checked = false;

        Object.keys(formGroup.controls).forEach(key => {
          const control = formGroup.controls[key];
    
          if (control.value === true) {
            checked = true;
          }
        });

        if(!checked){
          return { requireOnetoBeChecked: true };
        }
        
        return null;
      };
    }

    /**
     * Sets the initial values for the branches
     * 
     * @param selectedBranches (dict): Dict of branches and their selection state
     */
    public setBranchState(selectedBranches){
        for(let controlName in this.branchForm.controls){
            if(controlName in selectedBranches){
                this.branchForm.controls[controlName].setValue(selectedBranches[controlName]);
            }
        }
    }
  }
