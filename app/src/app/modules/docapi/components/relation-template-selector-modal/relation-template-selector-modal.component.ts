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
import { Component, EventEmitter, Input, Output, OnDestroy, OnInit } from '@angular/core';
import { NgbActiveModal } from '@ng-bootstrap/ng-bootstrap';
import { finalize, Subject, takeUntil } from 'rxjs';
import { CmdbRelation } from 'src/app/framework/models/relation.model';
import { CmdbType } from 'src/app/framework/models/cmdb-type';
import { RelationService } from 'src/app/framework/services/relaion.service';
import { TypeService } from 'src/app/framework/services/type.service';
import { LoaderService } from 'src/app/core/services/loader.service';

interface RelationFieldOption {
  name: string;
  label: string;
  type?: string;
}

interface TypeFieldOption {
  name: string;
  label: string;
  type?: string;
}

interface RelationTemplateStep {
  baseTypeId: number;
  availableRelations: CmdbRelation[];
  relationId?: number;
  relation?: CmdbRelation;
  direction?: 'parent' | 'child';
  directionOptions?: Array<{ value: 'parent' | 'child'; label: string }>;
  availableTypes: CmdbType[];
  typeId?: number;
  typeFields: TypeFieldOption[];
  relationFields: RelationFieldOption[];
  outputKind?: 'field' | 'relation_field' | 'relation';
  fieldName?: string;
  relationFieldName?: string;
  loadingRelations?: boolean;
  loadingTypes?: boolean;
  loadingFields?: boolean;
}

@Component({
  selector: 'cmdb-relation-template-selector-modal',
  templateUrl: './relation-template-selector-modal.component.html',
  styleUrls: ['./relation-template-selector-modal.component.scss'],
  standalone: false
})
export class RelationTemplateSelectorModalComponent implements OnInit, OnDestroy {
  @Input() rootTypeId: number | null = null;
  @Output() insertTemplate = new EventEmitter<string>();

  public steps: RelationTemplateStep[] = [];
  public activeStepIndex = 0;
  public isLoading$ = this.loaderService.isLoading$;
  public readonly outputKindOptions = [
    { value: 'field', label: 'Object Field' },
    { value: 'relation_field', label: 'Relation Field' },
    { value: 'relation', label: 'Continue Path' }
  ];

  private destroy$ = new Subject<void>();

  constructor(
    public activeModal: NgbActiveModal,
    private relationService: RelationService,
    private typeService: TypeService,
    private loaderService: LoaderService
  ) {}

  ngOnInit(): void {
    if (this.rootTypeId) {
      this.initializeSteps(this.rootTypeId);
    }
  }

  ngOnDestroy(): void {
    this.destroy$?.next();
    this.destroy$?.complete();
  }

  get activeStep(): RelationTemplateStep | null {
    return this.steps[this.activeStepIndex] || null;
  }

  public initializeSteps(baseTypeId: number): void {
    this.steps = [this.createStep(baseTypeId)];
    this.activeStepIndex = 0;
    this.loadRelationsForStep(0);
  }

  public setActiveStep(index: number): void {
    if (index < 0 || index >= this.steps.length) {
      return;
    }
    this.activeStepIndex = index;
    this.ensureStepDataLoaded(index);
  }

  public onRelationSelect(stepIndex: number, relationIdValue: string): void {
    const step = this.steps[stepIndex];
    if (!step) {
      return;
    }
    const relationId = parseInt(relationIdValue, 10);
    if (!relationId) {
      this.resetStepFromRelation(stepIndex);
      return;
    }
    step.relationId = relationId;
    const relation = step.availableRelations.find(rel => rel.public_id === relationId);
    step.relation = relation;
    step.direction = undefined;
    step.directionOptions = this.getDirectionOptions(step);
    step.availableTypes = [];
    step.typeId = undefined;
    step.typeFields = [];
    step.relationFields = this.buildRelationFields(relation);
    step.outputKind = undefined;
    step.fieldName = undefined;
    step.relationFieldName = undefined;
    this.removeStepsAfter(stepIndex);
  }

  public onDirectionSelect(stepIndex: number, direction: 'parent' | 'child'): void {
    const step = this.steps[stepIndex];
    if (!step || !step.relation) {
      return;
    }
    step.direction = direction;
    step.typeId = undefined;
    step.availableTypes = [];
    step.typeFields = [];
    step.outputKind = undefined;
    step.fieldName = undefined;
    step.relationFieldName = undefined;
    this.removeStepsAfter(stepIndex);
    this.loadTypesForStep(stepIndex);
  }

  public onTypeSelect(stepIndex: number, typeIdValue: string): void {
    const step = this.steps[stepIndex];
    if (!step) {
      return;
    }
    const typeId = parseInt(typeIdValue, 10);
    if (!typeId) {
      step.typeId = undefined;
      step.typeFields = [];
      step.outputKind = undefined;
      step.fieldName = undefined;
      step.relationFieldName = undefined;
      this.removeStepsAfter(stepIndex);
      return;
    }
    step.typeId = typeId;
    step.outputKind = undefined;
    step.fieldName = undefined;
    step.relationFieldName = undefined;
    this.removeStepsAfter(stepIndex);
    this.loadTypeFields(stepIndex, typeId);
  }

  public onOutputKindSelect(stepIndex: number, kind: 'field' | 'relation_field' | 'relation'): void {
    const step = this.steps[stepIndex];
    if (!step || !step.typeId) {
      return;
    }
    step.outputKind = kind;
    step.fieldName = undefined;
    step.relationFieldName = undefined;

    if (kind === 'relation') {
      this.addNestedStep(stepIndex);
    } else {
      this.removeStepsAfter(stepIndex);
    }
  }

  public onFieldSelect(stepIndex: number, fieldName: string): void {
    const step = this.steps[stepIndex];
    if (!step) {
      return;
    }
    step.fieldName = fieldName || undefined;
  }

  public onRelationFieldSelect(stepIndex: number, fieldName: string): void {
    const step = this.steps[stepIndex];
    if (!step) {
      return;
    }
    step.relationFieldName = fieldName || undefined;
  }

  public removeLastStep(): void {
    if (this.steps.length <= 1) {
      return;
    }
    this.steps = this.steps.slice(0, -1);
    this.activeStepIndex = Math.min(this.activeStepIndex, this.steps.length - 1);
    const last = this.steps[this.steps.length - 1];
    if (last) {
      last.outputKind = undefined;
      last.fieldName = undefined;
      last.relationFieldName = undefined;
    }
  }

  public insert(): void {
    const template = this.previewTemplate;
    if (!template) {
      return;
    }
    this.insertTemplate.emit(template);
    this.activeModal.close();
  }

  public cancel(): void {
    this.activeModal.dismiss();
  }

  public getDirectionLabel(step: RelationTemplateStep, direction: 'parent' | 'child'): string {
    if (!step?.relation) {
      return direction === 'parent' ? 'Parent' : 'Child';
    }
    return direction === 'parent'
      ? `Parent (${step.relation.relation_name_parent || 'parent'})`
      : `Child (${step.relation.relation_name_child || 'child'})`;
  }

  public getCurrentSideLabel(relation: CmdbRelation, side: 'parent' | 'child'): string {
    if (!relation) {
      return side === 'parent' ? 'Parent' : 'Child';
    }
    return side === 'parent'
      ? `Parent (${relation.relation_name_parent || 'parent'})`
      : `Child (${relation.relation_name_child || 'child'})`;
  }

  public getDirectionOptions(step: RelationTemplateStep | null): Array<{ value: 'parent' | 'child'; label: string }> {
    if (!step?.relation) {
      return [];
    }
    const options: Array<{ value: 'parent' | 'child'; label: string }> = [];
    if (step.relation.parent_type_ids?.includes(step.baseTypeId)) {
      options.push({ value: 'child', label: this.getCurrentSideLabel(step.relation, 'parent') });
    }
    if (step.relation.child_type_ids?.includes(step.baseTypeId)) {
      options.push({ value: 'parent', label: this.getCurrentSideLabel(step.relation, 'child') });
    }
    return options;
  }

  public normalizeDirectionSelection(selection: any): 'parent' | 'child' | undefined {
    if (!selection) {
      return undefined;
    }
    if (typeof selection === 'string') {
      return selection as 'parent' | 'child';
    }
    return selection.value as 'parent' | 'child';
  }

  public getStepLabel(step: RelationTemplateStep, index: number): string {
    const relationName = step.relation?.relation_name || 'Select relation';
    const directionLabel = step.direction ? step.direction : 'direction';
    const typeLabel = step.typeId ? `type ${step.typeId}` : 'type';
    return `Step ${index + 1}: ${relationName} / ${directionLabel} / ${typeLabel}`;
  }

  public getStepCrumbLabel(step: RelationTemplateStep, index: number): string {
    const relationName = step.relation?.relation_name || 'Relation';
    const directionLabel = step.direction ? step.direction : 'direction';
    return `${index + 1}. ${relationName} • ${directionLabel}`;
  }

  public get previewTemplate(): string | null {
    const template = this.buildTemplate();
    return template ? `{{ ${template} }}` : null;
  }

  private createStep(baseTypeId: number): RelationTemplateStep {
    return {
      baseTypeId,
      availableRelations: [],
      availableTypes: [],
      typeFields: [],
      relationFields: [],
      directionOptions: [],
      loadingRelations: false,
      loadingTypes: false,
      loadingFields: false
    };
  }

  private resetStepFromRelation(stepIndex: number): void {
    const step = this.steps[stepIndex];
    if (!step) {
      return;
    }
    step.relationId = undefined;
    step.relation = undefined;
    step.direction = undefined;
    step.directionOptions = [];
    step.availableTypes = [];
    step.typeId = undefined;
    step.typeFields = [];
    step.relationFields = [];
    step.outputKind = undefined;
    step.fieldName = undefined;
    step.relationFieldName = undefined;
    this.removeStepsAfter(stepIndex);
  }

  private loadRelationsForStep(stepIndex: number): void {
    const step = this.steps[stepIndex];
    if (!step?.baseTypeId) {
      return;
    }
    step.loadingRelations = true;
    this.loaderService.show();
    const params = {
      filter: {
        $or: [
          { parent_type_ids: { $in: [step.baseTypeId] } },
          { child_type_ids: { $in: [step.baseTypeId] } }
        ]
      },
      limit: 0,
      sort: 'public_id',
      order: 1,
      page: 1
    };

    this.relationService.getRelations(params)
      .pipe(
        takeUntil(this.destroy$),
        finalize(() => {
          step.loadingRelations = false;
          this.loaderService.hide();
        })
      )
      .subscribe({
        next: (response) => {
          const relations = response?.results || [];
          step.availableRelations = relations.map((relation) => ({
            ...relation,
            displayLabel: relation?.relation_name || `Relation ${relation?.public_id}`
          }));
          if (step.relationId) {
            const matched = step.availableRelations.find(rel => rel.public_id === step.relationId);
            if (matched) {
              step.relation = matched;
            }
          } else if (step.relation?.public_id) {
            step.relationId = step.relation.public_id;
          }
        },
        error: () => {
          step.availableRelations = [];
        }
      });
  }

  private loadTypesForStep(stepIndex: number): void {
    const step = this.steps[stepIndex];
    if (!step?.relation || !step.direction) {
      return;
    }
    const typeIds = step.direction === 'parent'
      ? (step.relation.parent_type_ids || [])
      : (step.relation.child_type_ids || []);

    if (!typeIds.length) {
      step.availableTypes = [];
      return;
    }

    step.loadingTypes = true;
    this.loaderService.show();
    const params = {
      filter: { public_id: { $in: typeIds } },
      limit: 0,
      sort: 'public_id',
      order: 1,
      page: 1
    } as any;

    this.typeService.getTypes(params)
      .pipe(
        takeUntil(this.destroy$),
        finalize(() => {
          step.loadingTypes = false;
          this.loaderService.hide();
        })
      )
      .subscribe({
        next: (response: any) => {
          const types = response?.results || [];
          step.availableTypes = types.map((type) => ({
            ...type,
            displayLabel: type?.label || type?.name || type?.public_id
          }));
        },
        error: () => {
          step.availableTypes = [];
        }
      });
  }

  private loadTypeFields(stepIndex: number, typeId: number): void {
    const step = this.steps[stepIndex];
    if (!step) {
      return;
    }
    step.loadingFields = true;
    this.loaderService.show();
    this.typeService.getType(typeId)
      .pipe(
        takeUntil(this.destroy$),
        finalize(() => {
          step.loadingFields = false;
          this.loaderService.hide();
        })
      )
      .subscribe({
        next: (type: CmdbType) => {
          const fields = Array.isArray(type?.fields) ? type.fields : [];
          const fieldOptions = fields.map(field => ({
            name: field.name,
            label: field.label || field.name,
            type: field.type
          }));
          step.typeFields = [{ name: 'public_id', label: 'Public ID', type: 'public_id' }, ...fieldOptions];
        },
        error: () => {
          step.typeFields = [{ name: 'public_id', label: 'Public ID', type: 'public_id' }];
        }
      });
  }

  private addNestedStep(stepIndex: number): void {
    const step = this.steps[stepIndex];
    if (!step?.typeId) {
      return;
    }
    const nextIndex = stepIndex + 1;
    if (this.steps.length > nextIndex) {
      this.steps = this.steps.slice(0, nextIndex);
    }
    const nextStep = this.createStep(step.typeId);
    this.steps.push(nextStep);
    this.activeStepIndex = nextIndex;
    this.loadRelationsForStep(nextIndex);
  }

  private removeStepsAfter(stepIndex: number): void {
    if (this.steps.length <= stepIndex + 1) {
      return;
    }
    this.steps = this.steps.slice(0, stepIndex + 1);
    this.activeStepIndex = Math.min(this.activeStepIndex, this.steps.length - 1);
  }

  private buildRelationFields(relation?: CmdbRelation): RelationFieldOption[] {
    if (!relation?.fields?.length) {
      return [];
    }
    return relation.fields.map(field => ({
      name: field.name,
      label: field.label || field.name,
      type: field.type
    }));
  }

  private ensureStepDataLoaded(stepIndex: number): void {
    const step = this.steps[stepIndex];
    if (!step) {
      return;
    }
    if (!step.availableRelations.length) {
      this.loadRelationsForStep(stepIndex);
    }
    if (!step.relation && step.relationId && step.availableRelations.length) {
      step.relation = step.availableRelations.find(rel => rel.public_id === step.relationId);
    }
    if (step.relation && (!step.directionOptions || step.directionOptions.length === 0)) {
      step.directionOptions = this.getDirectionOptions(step);
    }
    if (step.relation && step.relationFields.length === 0) {
      step.relationFields = this.buildRelationFields(step.relation);
    }
    if (step.relation && step.direction && step.availableTypes.length === 0) {
      this.loadTypesForStep(stepIndex);
    }
    if (step.typeId && step.typeFields.length === 0) {
      this.loadTypeFields(stepIndex, step.typeId);
    }
  }

  private buildTemplate(): string | null {
    if (!this.steps.length) {
      return null;
    }
    let template = 'root';

    for (let index = 0; index < this.steps.length; index += 1) {
      const step = this.steps[index];
      if (!step?.relation || !step.direction || !step.typeId) {
        return null;
      }
      template += `.relation(${step.relation.public_id}, '${step.direction}')`;
      template += `.type(${step.typeId})`;

      const isLast = index === this.steps.length - 1;

      if (!isLast) {
        if (step.outputKind !== 'relation') {
          return null;
        }
        continue;
      }

      if (step.outputKind === 'field') {
        if (!step.fieldName) {
          return null;
        }
        if (step.fieldName === 'public_id') {
          template += '.public_id';
        } else {
          template += `.fields['${step.fieldName}']`;
        }
      } else if (step.outputKind === 'relation_field') {
        if (!step.relationFieldName) {
          return null;
        }
        template += `.relation_fields['${step.relationFieldName}']`;
      } else {
        return null;
      }
    }

    return template;
  }
}
