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
import { ReplaySubject, Subscription } from 'rxjs';
import { TypeBuilderStepComponent } from '../type-builder-step.component';
import { finalize, take, takeUntil } from 'rxjs/operators';
import { CmdbType } from '../../../models/cmdb-type';
import { alphanumericValidator } from './alphanumeric-validator';
import { SpecialType, SpecialTypeOption, SpecialTypeSchema } from '../../../models/special-type';
import { SpecialTypeService } from '../../../services/special-type.service';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { LoaderService } from 'src/app/core/services/loader.service';
import { LicenseFeature } from 'src/app/settings/license-management/models/license.model';
import { PremiumFeatureService } from 'src/app/settings/license-management/premium-feature/premium-feature.service';
import { ValidationService } from '../../services/validation.service';
import { SpecialTypeSchemaContent, SpecialTypeSchemaMapper } from '../utils/special-type-schema.mapper';


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
  // Special types (subnets/supernets) belong to IPAM; when locked the dropdown is shown as a Pro upsell.
  public ipamAvailable = false;

  public lockedSpecialTypeOptions: Array<SpecialTypeOption & { disabled: true }> = [];

  private specialTypeSchemaFieldNames: Set<string> = new Set<string>();
  private specialTypeSchemaSectionNames: Set<string> = new Set<string>();
  private previouslySelectedSpecialType: SpecialType | null = null;
  private latestSpecialTypeRequestId = 0;
  private specialTypeSchemaRequest: Subscription | null = null;


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
    private toastService: ToastService,
    private loaderService: LoaderService,
    private validationService: ValidationService,
    private premiumFeatureService: PremiumFeatureService
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
      this.watchIpamAvailability();
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

    // New type should start with a distinct random color
    if (this.mode === CmdbMode.Create && !this.typeInstance?.ci_explorer_color) {
      this.setRandomColor();
    }
  }


  public ngOnDestroy(): void {
    this.specialTypeSchemaRequest?.unsubscribe();
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
    // Pad to a full 6-digit hex so the value is always a valid <input type="color"> color,
    // even when the generated number is small (e.g. avoids "#64" being rendered as black).
    const randomColor = '#' + Math.floor(Math.random() * 0x1000000).toString(16).padStart(6, '0');
    this.form.get('ci_explorer_color').setValue(randomColor);
  }


  /** Opens the upgrade showcase for IPAM from the locked special-type field. */
  public promptIpamUpgrade(): void {
    this.premiumFeatureService.promptUpgrade(LicenseFeature.Ipam);
  }


  /**
   * Tracks IPAM entitlement so the special-type dropdown renders functionally only when unlocked,
   * and as a "Pro" upsell otherwise. The available special types are loaded from the backend either
   * way so the locked dropdown lists the same options.
   */
  private watchIpamAvailability(): void {
    this.premiumFeatureService.isAvailable$(LicenseFeature.Ipam)
      .pipe(takeUntil(this.subscriber))
      .subscribe((available) => {
        this.ipamAvailable = available;

        if (!this.specialTypeOptions.length) {
          this.loadAvailableSpecialTypes();
        }
      });
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
        this.lockedSpecialTypeOptions = this.specialTypeOptions.map((option) => ({ ...option, disabled: true }));
      },
      error: (error) => {
        this.toastService.error(error?.error?.message);
      }
    });
  }


  private handleSpecialTypeChange(specialType: SpecialType | null): void {
    const normalizedSpecialType = this.normalizeSpecialTypeValue(specialType);

    if (
      normalizedSpecialType === this.previouslySelectedSpecialType
      && this.isCurrentSpecialTypeSchemaApplied(normalizedSpecialType)
    ) {
      return;
    }

    if (!normalizedSpecialType) {
      this.latestSpecialTypeRequestId++;
      this.specialTypeSchemaRequest?.unsubscribe();
      this.loaderService.hide();
      this.removeSpecialTypeSchemaFromType();
      this.previouslySelectedSpecialType = null;
      return;
    }

    const requestId = ++this.latestSpecialTypeRequestId;
    this.specialTypeSchemaRequest?.unsubscribe();

    const cachedSchema = this.specialTypeService.getCachedSchema(normalizedSpecialType);
    if (cachedSchema) {
      if (!this.applySchemaIfValid(cachedSchema, normalizedSpecialType)) {
        this.specialType.patchValue(this.previouslySelectedSpecialType, { emitEvent: false });
      }

      return;
    }

    this.loaderService.show();
    this.specialTypeSchemaRequest = this.specialTypeService.getSchema(normalizedSpecialType).pipe(
      take(1),
      finalize(() => this.loaderService.hide())
    ).subscribe({
      next: (schema: SpecialTypeSchema) => {
        if (requestId !== this.latestSpecialTypeRequestId) {
          return;
        }

        if (!this.applySchemaIfValid(schema, normalizedSpecialType)) {
          this.specialType.patchValue(this.previouslySelectedSpecialType, { emitEvent: false });
          return;
        }
      },
      error: (error) => {
        if (requestId !== this.latestSpecialTypeRequestId) {
          return;
        }

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


  private clearTypeContentBeforeSpecialSchemaPatch(): void {
    this.typeInstance.render_meta.sections = [];
    this.typeInstance.fields = [];
    this.specialTypeSchemaSectionNames = new Set<string>();
    this.specialTypeSchemaFieldNames = new Set<string>();
  }


  private applySpecialTypeSchemaToType(schemaContent: SpecialTypeSchemaContent): void {
    this.typeInstance.fields = [...schemaContent.fields];
    this.typeInstance.render_meta = {
      ...this.typeInstance.render_meta,
      sections: [...schemaContent.sections]
    };

    this.specialTypeSchemaSectionNames = schemaContent.sectionNames;
    this.specialTypeSchemaFieldNames = schemaContent.fieldNames;
  }


  private setActiveSpecialType(specialType: SpecialType): void {
    this.typeInstance.special_type = specialType;
    this.previouslySelectedSpecialType = specialType;

    if (specialType === SpecialType.RACK) {
      this.enforceRackParentSelection();
    }

    this.validationService.setSectionHighlightState(false);
    this.validationService.setFieldHighlightState(false);
  }


  /**
   * A rack carries its mounted objects through their location nodes, so a rack type has to stay
   * selectable as a parent location.
   */
  private enforceRackParentSelection(): void {
    this.typeInstance.selectable_as_parent = true;

    // The location field config seeds its toggle from the field, so keep both in sync.
    (this.typeInstance.fields ?? [])
      .filter((field) => field?.type === 'location')
      .forEach((field) => field.selectable_as_parent = true);
  }


  private isCurrentSpecialTypeSchemaApplied(specialType: SpecialType | null): boolean {
    if (!specialType) {
      return false;
    }

    const schema = this.specialTypeService.getCachedSchema(specialType);
    if (!SpecialTypeSchemaMapper.isValidSchemaShape(schema) || !SpecialTypeSchemaMapper.validateSchema(schema).valid) {
      return false;
    }

    return SpecialTypeSchemaMapper.createTypeContentSignature(this.typeInstance) === SpecialTypeSchemaMapper.buildContent(schema).signature;
  }


  private applySchemaIfValid(schema: SpecialTypeSchema, specialType: SpecialType): boolean {
    const validationResult = SpecialTypeSchemaMapper.validateSchema(schema);
    if (!validationResult.valid) {
      this.toastService.error(validationResult.message ?? 'Received an invalid special type schema from backend.');
      return false;
    }

    const schemaContent = SpecialTypeSchemaMapper.buildContent(schema);
    this.clearTypeContentBeforeSpecialSchemaPatch();
    this.applySpecialTypeSchemaToType(schemaContent);
    this.setActiveSpecialType(specialType);
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
