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

import { Component, Input, OnDestroy, OnInit } from '@angular/core';
import { UntypedFormControl, UntypedFormGroup, Validators } from '@angular/forms';
import { checkTypeExistsValidator, TypeService } from '../../../services/type.service';
import { CmdbMode } from '../../../modes.enum';
import { ReplaySubject } from 'rxjs';
import { TypeBuilderStepComponent } from '../type-builder-step.component';
import { takeUntil } from 'rxjs/operators';
import { take } from 'rxjs/operators';
import { CmdbType } from '../../../models/cmdb-type';
import { alphanumericValidator } from './alphanumeric-validator';
import { SpecialType, SpecialTypeOption, SpecialTypeSchema } from '../../../models/special-type';
import { SpecialTypeService } from '../../../services/special-type.service';
import { ToastService } from 'src/app/layout/toast/toast.service';


/**
 * Type builder step for basic type information.
 */
@Component({
    selector: 'cmdb-type-basic-step',
    templateUrl: './type-basic-step.component.html',
    styleUrls: ['./type-basic-step.component.scss'],
    standalone: false
})
export class TypeBasicStepComponent extends TypeBuilderStepComponent implements OnInit, OnDestroy {

  private subscriber: ReplaySubject<void> = new ReplaySubject<void>();
  public readonly modes = CmdbMode;
  public form: UntypedFormGroup;
  public specialTypeOptions: Array<SpecialTypeOption> = [];

  private specialTypeSchemaFieldNames: Set<string> = new Set<string>();
  private specialTypeSchemaSectionNames: Set<string> = new Set<string>();
  private previouslySelectedSpecialType: SpecialType | null = null;


  @Input('typeInstance')
  public set TypeInstance(instance: CmdbType) {
    if (instance) {
      this.typeInstance = instance;
      const normalizedSpecialType = this.normalizeSpecialTypeValue(instance.special_type);
      this.previouslySelectedSpecialType = normalizedSpecialType;
      this.form.patchValue({
        name: this.typeInstance.name,
        label: this.typeInstance.label,
        description: this.typeInstance.description,
        active: this.typeInstance.active,
        icon: this.typeInstance.render_meta.icon,
        ci_explorer_color: instance.ci_explorer_color || '#8896a5',  // fallback
        special_type: this.mode === CmdbMode.Create ? normalizedSpecialType : null
      });
    }
  }


  constructor(
    private typeService: TypeService,
    private specialTypeService: SpecialTypeService,
    private toastService: ToastService
  ) {
    super();
    this.form = new UntypedFormGroup({
      name: new UntypedFormControl('', [Validators.required, alphanumericValidator()]),
      label: new UntypedFormControl('', Validators.required),
      special_type: new UntypedFormControl(null),
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
      this.loadAvailableSpecialTypes();
      this.form.get('special_type').valueChanges.pipe(takeUntil(this.subscriber)).subscribe((specialType: SpecialType | null) => {
        this.handleSpecialTypeChange(specialType);
      });
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
    if (this.mode === CmdbMode.Create) {
      this.typeInstance.special_type = this.normalizeSpecialTypeValue(changes.special_type) ?? undefined;
    }
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

  public get specialType(): UntypedFormControl {
    return this.form.get('special_type') as UntypedFormControl;
  }


  /**
   * Sets a random color for the type's CI Explorer color field.
   */
  public setRandomColor(): void {
    const randomColor = '#' + Math.floor(Math.random() * 16777215).toString(16);
    this.form.get('ci_explorer_color').setValue(randomColor);
  }


  private loadAvailableSpecialTypes(): void {
    this.specialTypeService.getAvailableSpecialTypes().pipe(takeUntil(this.subscriber)).subscribe({
      next: (specialTypes: Record<string, string>) => {
        const availableTypes = specialTypes ?? {};
        this.specialTypeOptions = Object.entries(availableTypes).map(([type, description]) => ({
          value: type as SpecialType,
          label: `${type} - ${description}`,
          description
        }));
      },
      error: (error) => {
        this.toastService.error(error?.error?.message);
      }
    });
  }


  private handleSpecialTypeChange(specialType: SpecialType | null): void {
    const normalizedSpecialType = this.normalizeSpecialTypeValue(specialType);

    if (normalizedSpecialType === this.previouslySelectedSpecialType) {
      return;
    }

    if (!normalizedSpecialType) {
      this.removeSpecialTypeSchemaFromType();
      this.previouslySelectedSpecialType = null;
      return;
    }

    this.specialTypeService.getSchema(normalizedSpecialType).pipe(take(1)).subscribe({
      next: (schema: SpecialTypeSchema) => {
        if (!schema || !Array.isArray(schema.sections) || !Array.isArray(schema.fields)) {
          this.specialType.patchValue(this.previouslySelectedSpecialType, { emitEvent: false });
          this.toastService.error('Received an invalid special type schema from backend.');
          return;
        }

        const applied = this.applySpecialTypeSchemaToType(schema);
        if (!applied) {
          this.specialType.patchValue(this.previouslySelectedSpecialType, { emitEvent: false });
          return;
        }

        this.typeInstance.special_type = normalizedSpecialType;
        this.previouslySelectedSpecialType = normalizedSpecialType;
      },
      error: (error) => {
        this.specialType.patchValue(this.previouslySelectedSpecialType, { emitEvent: false });
        this.toastService.error(error?.error?.message || 'Failed to load special type schema.');
      }
    });
  }


  private removeSpecialTypeSchemaFromType(): void {
    this.typeInstance.render_meta.sections = this.typeInstance.render_meta.sections.filter(
      (section) => !this.specialTypeSchemaSectionNames.has(section.name)
    );
    this.typeInstance.fields = this.typeInstance.fields.filter(
      (field) => !this.specialTypeSchemaFieldNames.has(field.name)
    );
    this.typeInstance.special_type = undefined;
    this.specialTypeSchemaSectionNames = new Set<string>();
    this.specialTypeSchemaFieldNames = new Set<string>();
  }


  private applySpecialTypeSchemaToType(schema: SpecialTypeSchema): boolean {
    const customSections = this.typeInstance.render_meta.sections.filter(
      (section) => !this.specialTypeSchemaSectionNames.has(section.name)
    );
    const customFields = this.typeInstance.fields.filter(
      (field) => !this.specialTypeSchemaFieldNames.has(field.name)
    );

    const incomingSectionNames = new Set<string>(schema.sections.map(section => section.name));
    const incomingFieldNames = new Set<string>(schema.fields.map(field => field.name));
    const conflictingSection = customSections.find(section => incomingSectionNames.has(section.name));
    const conflictingField = customFields.find(field => incomingFieldNames.has(field.name));

    if (conflictingSection || conflictingField) {
      this.toastService.error('Cannot apply special type schema due to conflicting section or field identifiers.');
      return false;
    }

    const schemaFields = schema.fields.map(field => ({ ...field }));
    const schemaSections = schema.sections.map(section => ({
      ...section,
      fields: [...section.fields]
    }));

    this.typeInstance.fields = [...schemaFields, ...customFields];
    this.typeInstance.render_meta.sections = [...schemaSections, ...customSections];

    this.specialTypeSchemaSectionNames = incomingSectionNames;
    this.specialTypeSchemaFieldNames = incomingFieldNames;
    return true;
  }

  
  private normalizeSpecialTypeValue(value: string | SpecialType | null | undefined): SpecialType | null {
    if (!value || typeof value !== 'string') {
      return null;
    }

    const trimmedValue = value.trim();
    return trimmedValue ? (trimmedValue as SpecialType) : null;
  }

}
