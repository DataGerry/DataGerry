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

import { Component, Input, OnDestroy, OnInit } from '@angular/core';
import { UntypedFormControl, UntypedFormGroup, ValidationErrors, ValidatorFn, Validators } from '@angular/forms';
import { checkTypeExistsValidator, TypeService } from '../../../services/type.service';
import { CmdbMode } from '../../../modes.enum';
import { ReplaySubject } from 'rxjs';
import { TypeBuilderStepComponent } from '../type-builder-step.component';
import { takeUntil } from 'rxjs/operators';
import { CmdbType } from '../../../models/cmdb-type';
import { alphanumericValidator } from './alphanumeric-validator';


/**
 * Type builder step for basic type information.
 */
@Component({
  selector: 'cmdb-type-basic-step',
  templateUrl: './type-basic-step.component.html',
  styleUrls: ['./type-basic-step.component.scss'],
})
export class TypeBasicStepComponent extends TypeBuilderStepComponent implements OnInit, OnDestroy {

  private subscriber: ReplaySubject<void> = new ReplaySubject<void>();
  public form: UntypedFormGroup;


  @Input('typeInstance')
  public set TypeInstance(instance: CmdbType) {
    if (instance) {
      this.typeInstance = instance;
      this.form.patchValue({
        name: this.typeInstance.name,
        label: this.typeInstance.label,
        description: this.typeInstance.description,
        active: this.typeInstance.active,
        icon: this.typeInstance.render_meta.icon,
        ci_explorer_color: instance.ci_explorer_color || '#8896a5'  // fallback
      });
    }
  }


  constructor(private typeService: TypeService) {
    super();
    this.form = new UntypedFormGroup({
      name: new UntypedFormControl('', [Validators.required, alphanumericValidator()]),
      label: new UntypedFormControl('', Validators.required),
      description: new UntypedFormControl(''),
      active: new UntypedFormControl(true),
      icon: new UntypedFormControl('fa fa-cube'),
      ci_explorer_color: new UntypedFormControl('#8896a5')
    });
  }


  public ngOnInit(): void {
    if (this.mode === CmdbMode.Create) {
      this.form.get('name').setAsyncValidators(checkTypeExistsValidator(this.typeService));
      this.form.markAllAsTouched();
    } else if (this.mode === CmdbMode.Edit) {
      this.form.markAllAsTouched();
    }
    this.form.valueChanges.pipe(takeUntil(this.subscriber)).subscribe((changes: any) => {
      this.assign(changes);
    });
    this.form.statusChanges.pipe(takeUntil(this.subscriber)).subscribe(() => {
      this.validateChange.emit(this.form.valid);
      this.valid = this.form.valid;
    });
  }


  public ngOnDestroy(): void {
    this.subscriber?.next();
    this.subscriber?.complete();
  }


  /**
   * Assigns the form values to the type instance.
   */
  public assign(changes): void {
    this.typeInstance.name = changes.name;
    this.typeInstance.label = changes.label;
    this.typeInstance.description = changes.description;
    this.typeInstance.active = changes.active;
    this.typeInstance.render_meta.icon = changes.icon;
    this.typeInstance.ci_explorer_color = changes.ci_explorer_color;
  }

  public get icon(): UntypedFormControl {
    return this.form.get('icon') as UntypedFormControl;
  }

  public get name(): UntypedFormControl {
    return this.form.get('name') as UntypedFormControl;
  }

  public get label(): UntypedFormControl {
    return this.form.get('label') as UntypedFormControl;
  }

  public get description(): UntypedFormControl {
    return this.form.get('description') as UntypedFormControl;
  }


  /**
   * Sets a random color for the type's CI Explorer color field.
   */
  public setRandomColor(): void {
    const randomColor = '#' + Math.floor(Math.random() * 16777215).toString(16);
    this.form.get('ci_explorer_color').setValue(randomColor);
  }
  
}
