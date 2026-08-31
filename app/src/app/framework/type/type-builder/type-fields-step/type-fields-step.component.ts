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
* along with this program. If not, see <https://www.gnu.org/licenses/>.
*/
import { Component, DoCheck, Input, KeyValueDiffer, KeyValueDiffers, OnDestroy, OnInit } from '@angular/core';

import { ReplaySubject, Subscription } from 'rxjs';
import { take, takeUntil } from 'rxjs/operators';

import { SectionTemplateService } from 'src/app/framework/section_templates/services/section-template.service';

import { TypeBuilderStepComponent } from '../type-builder-step.component';
import { CmdbType } from '../../../models/cmdb-type';
import { CmdbSectionTemplate } from 'src/app/framework/models/cmdb-section-template';
import { APIGetMultiResponse } from 'src/app/services/models/api-response';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { SpecialTypeService } from '../../../services/special-type.service';
import { SpecialType, SpecialTypeSchema } from '../../../models/special-type';
import { SpecialTypeSchemaMapper } from '../utils/special-type-schema.mapper';
import { LocationFieldDeletionService } from '../../services/location-field-deletion.service';
import { BUILDER_DELETION_GUARD, BuilderDeletionGuard } from 'src/app/framework/builder/services/builder-deletion-guard';
import { CmdbTypeSchemaAdapter } from 'src/app/framework/builder/schema/cmdb-type-schema.adapter';
import { BuilderSchemaAdapter } from 'src/app/framework/builder/schema/builder-schema.adapter';
import { SectionControl } from 'src/app/framework/builder/controls/section.control';
import { MultiSectionControl } from 'src/app/framework/builder/controls/multi-section.control';
import { RefSectionControl } from 'src/app/framework/builder/controls/ref-section.common';
import { ReferenceControl } from 'src/app/framework/builder/controls/specials/ref.control';
import { LocationControl } from 'src/app/framework/builder/controls/specials/location.control';
import { BASIC_CONTROLS } from 'src/app/framework/builder/controls/basic-controls';
import {
    BuilderPaletteGroup,
    paletteItemsFromControls,
    paletteItemsFromSectionTemplates
} from 'src/app/framework/builder/palette/builder-palette.model';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'cmdb-type-fields-step',
    templateUrl: './type-fields-step.component.html',
    styleUrls: ['./type-fields-step.component.scss'],
    // Only the type builder guards a deletion: a persisted location field still referenced by objects.
    // Typed factory rather than `useExisting`, whose `any` typing would not catch the service
    // drifting out of shape with BuilderDeletionGuard.
    providers: [{
        provide: BUILDER_DELETION_GUARD,
        useFactory: (guard: LocationFieldDeletionService): BuilderDeletionGuard => guard,
        deps: [LocationFieldDeletionService]
    }],
    standalone: false
})
export class TypeFieldsStepComponent extends TypeBuilderStepComponent implements OnInit, DoCheck, OnDestroy {

  private subscriber: ReplaySubject<void> = new ReplaySubject<void>();
  private unsubscribe: ReplaySubject<void> = new ReplaySubject<void>();
  private typeInstanceDiffer: KeyValueDiffer<string, any>;

  public sectionTemplates: Array<CmdbSectionTemplate> = [];
  public globalSectionTemplates: Array<CmdbSectionTemplate> = [];
  public lockedSectionNames: Array<string> = [];
  public lockedFieldNames: Array<string> = [];
  private activeSpecialTypeForLocks: SpecialType | null = null;
  private failedSpecialTypeForLocks: SpecialType | null = null;
  private specialTypeSchemaRequest: Subscription | null = null;

  public builderValid: boolean = true;

  public schema: BuilderSchemaAdapter | null = null;

  @Input('typeInstance')
  public set TypeInstance(instance: CmdbType) {
    if (instance) {
      this.typeInstance = instance;
      this.typeInstanceDiffer = this.differs.find(this.typeInstance).create();
      this.schema = new CmdbTypeSchemaAdapter(this.typeInstance);
    }
  }

  private readonly structureItems = paletteItemsFromControls([
    new SectionControl(),
    new MultiSectionControl(),
    new RefSectionControl()
  ]);

  private readonly basicItems = paletteItemsFromControls(BASIC_CONTROLS);

  private readonly specialItems = paletteItemsFromControls([
    new ReferenceControl(),
    new LocationControl()
  ]);

  private cachedPaletteGroups: Array<BuilderPaletteGroup> | null = null;
  private cachedPaletteKey: string | null = null;

  /**
   * The canvas mutates the two template arrays in place as templates are applied and released, so
   * the palette has to re-read them. It must NOT return a fresh array every check though: the
   * canvas is OnPush, and a changing input reference marks it - and its whole section subtree -
   * dirty on every tick. So the result is cached against the only things that can change it.
   */
  public get paletteGroups(): Array<BuilderPaletteGroup> {
    const key = this.buildPaletteKey();

    if (this.cachedPaletteGroups && this.cachedPaletteKey === key) {
      return this.cachedPaletteGroups;
    }

    this.cachedPaletteKey = key;
    this.cachedPaletteGroups = [
      {
        id: 'globalSectionTemplates',
        label: 'Global Section Templates',
        expanded: true,
        items: paletteItemsFromSectionTemplates(this.globalSectionTemplates)
      },
      {
        id: 'sectionTemplates',
        label: 'Section Templates',
        items: paletteItemsFromSectionTemplates(this.sectionTemplates)
      },
      {
        id: 'structureControls',
        label: 'Structure Controls',
        lockMode: 'draggable-attr',
        items: this.structureItems
      },
      {
        id: 'basicControls',
        label: 'Basic Controls',
        items: this.basicItems
      },
      {
        id: 'specialControls',
        label: 'Special Controls',
        lockMode: 'draggable-attr',
        items: this.specialItems
      }
    ];

    return this.cachedPaletteGroups;
  }


  /** Identifies the palette's template contents: which templates, in which order. */
  private buildPaletteKey(): string {
    const names = (templates: Array<CmdbSectionTemplate>) =>
      (templates ?? []).map(template => template?.public_id).join(',');

    return `${names(this.globalSectionTemplates)}|${names(this.sectionTemplates)}`;
  }

/* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */
    public constructor(private differs: KeyValueDiffers,
                       private sectionTemplateService: SectionTemplateService,
                       private toastService: ToastService,
                       private specialTypeService: SpecialTypeService) {
        super();
    }


    public ngOnInit(): void {
        this.typeInstanceDiffer = this.differs.find(this.typeInstance).create();
        this.getAllSectionTemplates();
        this.syncSpecialTypeLockState();

    }


    public ngDoCheck(): void {
        const changes = this.typeInstanceDiffer.diff(this.typeInstance);
        if (changes) {
            this.syncSpecialTypeLockState();
            this.valid = this.status;
            this.validateChange.emit(this.valid);
        }
      }


    public ngOnDestroy(): void {
        this.specialTypeSchemaRequest?.unsubscribe();
        this.subscriber?.next();
        this.subscriber?.complete();
        this.unsubscribe?.next();
        this.unsubscribe?.complete();
    }

/* ---------------------------------------------------- FUCNTIONS --------------------------------------------------- */

    public get status(): boolean{
        const hasFields: boolean = this.typeInstance.fields.length > 0;
        const hasSections: boolean = this.typeInstance.render_meta.sections.length > 0;

        return hasFields && hasSections && this.builderValid;
    }


    public onBuilderValidChange(status: boolean): void{
        this.builderValid = status;
        this.valid = this.status;
        this.validateChange.emit(this.valid);
    }


  private getAllSectionTemplates() {
    this.sectionTemplateService.getSectionTemplates().pipe(takeUntil(this.unsubscribe))
      .subscribe({
        next: (apiResponse: APIGetMultiResponse<CmdbSectionTemplate>) => {
          this.sectionTemplates = apiResponse.results.filter((template) => template.is_global == false);
          this.globalSectionTemplates = apiResponse.results.filter((template) => template.is_global == true);
        },
        error: (error) => this.toastService.error(error?.error?.message)
      });
  }

  private syncSpecialTypeLockState(): void {
    const selectedSpecialType = this.normalizeSpecialTypeValue(this.typeInstance?.special_type);
    if (
      selectedSpecialType === this.activeSpecialTypeForLocks
      && (this.lockedSectionNames.length > 0 || this.lockedFieldNames.length > 0)
    ) {
      return;
    }

    if (
      selectedSpecialType === this.activeSpecialTypeForLocks
      && this.specialTypeSchemaRequest
    ) {
      return;
    }

    if (!selectedSpecialType) {
      this.resetSpecialTypeLocks();
      return;
    }

    if (selectedSpecialType === this.failedSpecialTypeForLocks) {
      return;
    }

    if (selectedSpecialType !== this.activeSpecialTypeForLocks) {
      this.failedSpecialTypeForLocks = null;
    }

    this.activeSpecialTypeForLocks = selectedSpecialType;
    const cachedSchema = this.specialTypeService.getCachedSchema(selectedSpecialType);
    if (cachedSchema) {
      this.applySpecialTypeLocks(cachedSchema);
      return;
    }

    this.lockedSectionNames = [];
    this.lockedFieldNames = [];
    this.specialTypeSchemaRequest?.unsubscribe();
    this.specialTypeSchemaRequest = this.specialTypeService.getSchema(selectedSpecialType).pipe(
      take(1),
      takeUntil(this.subscriber)
    ).subscribe({
      next: (schema: SpecialTypeSchema) => {
        this.specialTypeSchemaRequest = null;
        if (selectedSpecialType !== this.activeSpecialTypeForLocks) {
          return;
        }

        this.applySpecialTypeLocks(schema);
      },
      error: (error) => {
        this.specialTypeSchemaRequest = null;
        if (selectedSpecialType !== this.activeSpecialTypeForLocks) {
          return;
        }

        this.resetSpecialTypeLocks();
        this.failedSpecialTypeForLocks = selectedSpecialType;
        this.toastService.error(error?.error?.message);
      }
    });
  }


  private applySpecialTypeLocks(schema: SpecialTypeSchema): void {
    const validationResult = SpecialTypeSchemaMapper.validateSchema(schema);
    if (!validationResult.valid) {
      this.lockedSectionNames = [];
      this.lockedFieldNames = [];
      this.failedSpecialTypeForLocks = this.activeSpecialTypeForLocks;
      return;
    }

    this.failedSpecialTypeForLocks = null;
    this.lockedSectionNames = schema.sections.map(section => section.name);
    this.lockedFieldNames = schema.fields.map(field => field.name);
  }


  private resetSpecialTypeLocks(): void {
    this.specialTypeSchemaRequest?.unsubscribe();
    this.specialTypeSchemaRequest = null;
    this.activeSpecialTypeForLocks = null;
    this.failedSpecialTypeForLocks = null;

    if (this.lockedSectionNames.length !== 0) {
      this.lockedSectionNames = [];
    }
    if (this.lockedFieldNames.length !== 0) {
      this.lockedFieldNames = [];
    }
  }

  private normalizeSpecialTypeValue(value: string | SpecialType | null | undefined): SpecialType | null {
    if (!value || typeof value !== 'string') {
      return null;
    }

    const trimmedValue = value.trim();
    return trimmedValue ? (trimmedValue as SpecialType) : null;
  }
}
