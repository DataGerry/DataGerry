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

* You should have received a copy of the GNU Affero General Public License
* along with this program. If not, see <https://www.gnu.org/licenses/>.
*/

import { Component, Input, OnInit } from '@angular/core';
import { Group } from '../../../../../management/models/group';
import { AbstractControl, UntypedFormArray, UntypedFormControl, UntypedFormGroup, ValidatorFn, Validators } from '@angular/forms';
import { DndDropEvent } from 'ngx-drag-drop';

@Component({
    selector: 'cmdb-ldap-provider-form-group-mapping',
    templateUrl: './ldap-provider-form-group-mapping.component.html',
    styleUrls: ['./ldap-provider-form-group-mapping.component.scss'],
    standalone: false
})
export class LdapProviderFormGroupMappingComponent implements OnInit {

  /**
   * User management groups.
   */
  @Input() public groups: Array<Group> = [];

  /**
   * Parent mapping form.
   */
  @Input() public mappingForm: UntypedFormArray;

  /**
   * Mapping insert form.
   */
  public form: UntypedFormGroup;

  /**
   * OnInit for `LdapProviderFormGroupMappingComponent`.
   * Implements the insertion form for LDAP group mapping.
   */
  public ngOnInit(): void {
    this.form = new UntypedFormGroup({
      group_dn: new UntypedFormControl('', [
        Validators.required, this.dnAlreadyExistsValidator(this.mappingForm)]),
      group_id: new UntypedFormControl(null, Validators.required)
    });
  }

  /**
   * Get the control of the dn input field.
   */
  public get groupDNControl(): UntypedFormControl {
    return this.form.get('group_dn') as UntypedFormControl;
  }

  /**
   * Get the value of the dn input field.
   */
  public get groupDNValue(): string {
    return this.groupDNControl.value;
  }

  /**
   * Get the control of the group id field.
   */
  public get groupIDControl(): UntypedFormControl {
    return this.form.get('group_id') as UntypedFormControl;
  }

  /**
   * Get the value of the group public id input field.
   */
  public get groupIDValue(): number {
    return +this.groupIDControl.value;
  }

  /**
   * Inserts a new control into the parent `mappingForm` when valid.
   * Resets the insertion form `form` after that.
   */
  public addMapping(): void {
    if (this.form.valid) {
      const formGroup = new UntypedFormGroup({
        group_dn: new UntypedFormControl(this.groupDNValue),
        group_id: new UntypedFormControl(this.groupIDValue)
      });
      this.mappingForm.push(formGroup);
      this.form.reset();
    }
  }

  /**
   * Remove a mapping by delete the FormGroup from the mappingForm.
   * @param index
   */
  public removeMapping(index: number): void {
    this.mappingForm.removeAt(index);
  }

  /**
   * Get a group from the `groups` array by its public id.
   * @param publicID of the group.
   */
  public getGroupFromID(publicID: number): Group {
    return this.groups.find(g => g.public_id === publicID);
  }

  /**
   * Form validator which checks if the passed control parameter exists in a form group.
   * @param mapForm - passed `mappingForm` as `FormArray`.
   * @private
   */
  private dnAlreadyExistsValidator(mapForm: UntypedFormArray): ValidatorFn {
    return (control: AbstractControl): { [key: string]: any } | null => {
      let controlValue = control.value;
      if (controlValue) {
        controlValue = controlValue.toLowerCase();
      }
      const exists = mapForm.controls.map(c => c.get('group_dn').value.toLowerCase()).includes(controlValue);
      return exists ? { dnAlreadyExists: { value: control.value } } : null;
    };
  }

  public onDrop(event: DndDropEvent): void {
    const controlLength = this.mappingForm.controls.length;
    let index = event.index;

    if (typeof index === 'undefined' || index >= controlLength) {
      index = controlLength;
    }
    const selectedMapping = this.mappingForm.at(event.data);
    this.mappingForm.removeAt(event.data);
    this.mappingForm.insert(index, selectedMapping);

  }


}
