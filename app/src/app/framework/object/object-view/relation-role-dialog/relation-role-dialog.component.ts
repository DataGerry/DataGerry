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
import {
  Component,
  Input,
  Output,
  EventEmitter,
  OnInit,
  OnDestroy,
  computed,
  ChangeDetectionStrategy,
  ChangeDetectorRef
} from '@angular/core';
import { FormBuilder, FormGroup } from '@angular/forms';
import { finalize, Subject } from 'rxjs';
import { CmdbMode } from 'src/app/framework/modes.enum';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { CmdbRelation } from 'src/app/framework/models/relation.model';
import {
  ObjectRelationService,
  CmdbObjectRelationCreateDto
} from 'src/app/framework/services/object-relation.service';
import { UserService } from 'src/app/management/services/user.service';
import { LoaderService } from 'src/app/core/services/loader.service';

/**
 * Component for managing relationships between CMDB objects.
 * Supports creating, editing, and viewing relationships based on user selection.
 *
 * Object selection is delegated to the reusable app-object-selector, which
 * handles paginated loading, search and pre-selection of the chosen objects.
 */
@Component({
    selector: 'relation-role-dialog',
    templateUrl: './relation-role-dialog.component.html',
    styleUrls: ['./relation-role-dialog.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    standalone: false
})
export class RelationRoleDialogComponent implements OnInit, OnDestroy {
  @Input() chosenRole!: 'parent' | 'child' | 'both';
  @Input() parentTypeIDs: number[] = [];
  @Input() childTypeIDs: number[] = [];
  @Input() currentObjectID!: number;
  @Input() currentObjectTypeID!: number;
  @Input() relation: CmdbRelation = null;
  @Input() mode: CmdbMode = CmdbMode.Create;
  @Input() relationInstance: any = null; // Pre-filled relation instance

  @Output() onConfirm = new EventEmitter<{
    parentObjID: number;
    childObjID: number;
    relationData?: any;
  }>();
  @Output() onCancel = new EventEmitter<void>();

  public form: FormGroup;
  public relationForm: FormGroup;
  public sections: any[] = [];
  public CmdbMode = CmdbMode;

  // Object selector configuration (type scopes and pre-selected ids per side).
  public parentSelectorTypeIds: number[] = [];
  public childSelectorTypeIds: number[] = [];
  public parentSelectedIds: number[] = [];
  public childSelectedIds: number[] = [];

  public isLoading$ = this.loaderService.isLoading$;

  private destroy$ = new Subject<void>();
  private author_id: number;

  // Full objects behind the current selection, used to resolve the relation type ids.
  private selectedParentObject: any = null;
  private selectedChildObject: any = null;

  /**
   * Determines if the object can act as both parent and child.
   */
  public isBidirectional = computed(() =>
    this.parentTypeIDs.includes(this.currentObjectTypeID) &&
    this.childTypeIDs.includes(this.currentObjectTypeID)
  );

  constructor(
    private fb: FormBuilder,
    private toastService: ToastService,
    private objectRelationService: ObjectRelationService,
    private userService: UserService,
    private cdr: ChangeDetectorRef,
    private loaderService: LoaderService) {
    this.form = this.fb.group({
      parent: [null],
      child: [null]
    });
    this.relationForm = this.fb.group({});
    this.author_id = this.userService.getCurrentUser().public_id;
  }

  /* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

  ngOnInit(): void {
    this.initializeForms();
    this.setupVisibility();
    this.initializeSelectors();
    this.cdr.detectChanges();
  }

  ngOnDestroy(): void {
    this.destroy$?.next();
    this.destroy$?.complete();
  }

  /* ---------------------------------------------------- EVENTS ------------------------------------------------------ */

  public onParentSelectionChange(ids: number[]): void {
    this.form.get('parent')?.setValue(ids?.[0] ?? null);
  }

  public onChildSelectionChange(ids: number[]): void {
    this.form.get('child')?.setValue(ids?.[0] ?? null);
  }

  public onParentObjectChange(selection: any): void {
    this.selectedParentObject = Array.isArray(selection) ? selection[0] ?? null : selection;
  }

  public onChildObjectChange(selection: any): void {
    this.selectedChildObject = Array.isArray(selection) ? selection[0] ?? null : selection;
  }

  /* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

  /**
   * Handles confirmation action by emitting selected relation data.
   */
  confirm(): void {
    const parentObjID = this.form.get('parent')?.value ?? this.currentObjectID;
    const childObjID = this.form.get('child')?.value ?? this.currentObjectID;

    if (this.isBidirectional() && this.chosenRole === 'both') {
      if (!parentObjID && !childObjID) {
        this.toastService.error('Please select at least one relation');
        return;
      }
    }

    const parentTypeID = this.resolveTypeId(this.selectedParentObject, this.relationInstance?.relation_parent_type_id);
    const childTypeID = this.resolveTypeId(this.selectedChildObject, this.relationInstance?.relation_child_type_id);

    const formValue = this.relationForm.value;
    const field_values = Object.entries(formValue).map(([key, val]) => ({
      name: key,
      value: val != null ? val : ''
    }));

    const dto: CmdbObjectRelationCreateDto = {
      relation_id: this.relation.public_id,
      relation_parent_id: parentObjID,
      relation_child_id: childObjID,
      relation_parent_type_id: parentTypeID,
      relation_child_type_id: childTypeID,
      author_id: this.author_id,
      field_values
    } as any;

    if (this.mode === CmdbMode.Edit && this.relationInstance) {
      this.loaderService.show();
      (dto as any).public_id = this.relationInstance.public_id;
      this.objectRelationService.putObjectRelation(this.relationInstance.public_id, dto)
        .pipe(finalize(() => this.loaderService.hide()))
        .subscribe({
          next: (res) => {
            this.toastService.success(`Relation updated successfully`);
            this.onConfirm.emit({ parentObjID, childObjID, relationData: res });
          },
          error: (err) => {
            this.toastService.error(err?.error?.message);
          }
        });
    } else {
      this.loaderService.show();
      this.objectRelationService.postObjectRelation(dto)
        .pipe(finalize(() => this.loaderService.hide()))
        .subscribe({
          next: (res) => {
            this.toastService.success(`Relation created successfully`);
            this.onConfirm.emit({ parentObjID, childObjID, relationData: res });
          },
          error: (err) => {
            this.toastService.error(err?.error?.message);
          }
        });
    }
  }

  /**
   * Determines whether the confirm button should be disabled.
   */
  public isConfirmDisabled(): boolean {
    if (this.mode === CmdbMode.View) {
      return true;
    }
    if (this.chosenRole === 'parent') {
      const childValue = this.form.get('child')?.value;
      return !childValue || childValue === this.currentObjectID;
    } else if (this.chosenRole === 'child') {
      const parentValue = this.form.get('parent')?.value;
      return !parentValue || parentValue === this.currentObjectID;
    }
    return false;
  }

  /**
   * Emits a cancel event to close the dialog.
   */
  back(): void {
    this.onCancel.emit();
  }

  /**
   * Retrieves a field object by name from the relation definition.
   */
  public getFieldObject(fieldName: string) {
    return this.relation?.fields?.find(f => f.name === fieldName);
  }

  /**
   * Determines the current view mode.
   */
  public getViewMode(): CmdbMode {
    return this.mode === CmdbMode.View ? CmdbMode.View : CmdbMode.Edit;
  }

  /* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

  /**
   * Initializes the form and pre-fills values based on mode.
   */
  private initializeForms(): void {
    this.relationForm = this.fb.group({});
    if (this.relation?.sections) {
      this.sections = this.relation.sections;
      this.relation.fields?.forEach(field => {
        this.relationForm.addControl(field.name, this.fb.control(''));
      });
    }

    if (this.relationInstance) {
      this.form.patchValue({
        parent: this.relationInstance.relation_parent_id,
        child: this.relationInstance.relation_child_id
      });

      if (this.relationInstance.field_values && Array.isArray(this.relationInstance.field_values)) {
        const fieldValues = {};
        this.relationInstance.field_values.forEach(fv => {
          if (this.relationForm.contains(fv.name)) {
            fieldValues[fv.name] = fv.value;
          }
        });

        setTimeout(() => {
          this.relationForm.patchValue(fieldValues);
          this.cdr.detectChanges();
        }, 0);
      }

      // Set form state based on mode
      if (this.mode === CmdbMode.View) {
        this.form.disable();
        this.relationForm.disable();
      } else if (this.mode === CmdbMode.Edit) {
        if (this.chosenRole === 'parent') {
          this.form.get('parent')?.disable();
        } else if (this.chosenRole === 'child') {
          this.form.get('child')?.disable();
        }
      }
    } else {
      // For Create mode without instance
      if (this.chosenRole === 'parent') {
        this.form.get('parent')?.setValue(this.currentObjectID);
        this.form.get('parent')?.disable();
      } else if (this.chosenRole === 'child') {
        this.form.get('child')?.setValue(this.currentObjectID);
        this.form.get('child')?.disable();
      }
    }

    this.cdr.detectChanges();
  }

  /**
   * Enables both sides for bidirectional relations chosen as "both".
   */
  private setupVisibility(): void {
    if (this.isBidirectional() && this.chosenRole === 'both') {
      this.form.get('parent')?.enable();
      this.form.get('child')?.enable();
    }
  }

  /**
   * Prepares the type-id scopes and pre-selected ids for the object selectors.
   */
  private initializeSelectors(): void {
    this.parentSelectorTypeIds = this.validateTypeIDs(this.parentTypeIDs);
    this.childSelectorTypeIds = this.validateTypeIDs(this.childTypeIDs);

    this.parentSelectedIds = this.toSelectedIds(this.form.get('parent')?.value);
    this.childSelectedIds = this.toSelectedIds(this.form.get('child')?.value);
  }

  /**
   * Builds the selector pre-selection, ignoring the current object (which is
   * excluded from the options to prevent relating an object to itself).
   */
  private toSelectedIds(objectId: number | null | undefined): number[] {
    return objectId && objectId !== this.currentObjectID ? [objectId] : [];
  }

  /**
   * Resolves the relation type id from the actively selected object, falling
   * back to the stored instance type id and finally the current object type.
   */
  private resolveTypeId(selectedObject: any, fallbackTypeId?: number): number {
    return selectedObject?.type_information?.type_id
      ?? fallbackTypeId
      ?? this.currentObjectTypeID;
  }

  /**
   * Validates and extracts type IDs, ensuring they are positive integers.
   */
  private validateTypeIDs(ids: any[]): number[] {
    return (ids ?? []).flat(Infinity).filter((id: any) => Number.isInteger(id) && id > 0);
  }
}
