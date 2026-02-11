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
  ChangeDetectorRef,
  ViewChild
} from '@angular/core';
import { FormBuilder, FormGroup } from '@angular/forms';
import { debounceTime, distinctUntilChanged, finalize, Subject, takeUntil } from 'rxjs';
import { CmdbMode } from 'src/app/framework/modes.enum';
import { ObjectService } from 'src/app/framework/services/object.service';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { CmdbRelation } from 'src/app/framework/models/relation.model';
import {
  ObjectRelationService,
  CmdbObjectRelationCreateDto
} from 'src/app/framework/services/object-relation.service';
import { UserService } from 'src/app/management/services/user.service';
import { LoaderService } from 'src/app/core/services/loader.service';
import { CollectionParameters } from 'src/app/services/models/api-parameter';
import { APIGetMultiResponse } from 'src/app/services/models/api-response';
import { ObjectSearchFilterService } from 'src/app/core/services/object-search-filter.service';

interface FlatOptionItem {
  value: number;
  label: string;
  group: string;
}

/**
 * Component for managing relationships between CMDB objects.
 * Supports creating, editing, and viewing relationships based on user selection.
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
  public flatParentOptions: FlatOptionItem[] = [];
  public flatChildOptions: FlatOptionItem[] = [];
  public CmdbMode = CmdbMode;
  public loading = false;
  public showParentSection = false;
  public showChildSection = false;
  public parentIsLoading = false;
  public childIsLoading = false;
  public parentSearchSubject = new Subject<string>();
  public childSearchSubject = new Subject<string>();

  @ViewChild('parentSelect', { static: false }) public parentSelect: any;
  @ViewChild('childSelect', { static: false }) public childSelect: any;

  private destroy$ = new Subject<void>();
  private author_id: number;
  private initialLoadCount = 0;

  private parentPage = 1;
  private childPage = 1;
  private pageSize = 10;
  private parentHasMore = true;
  private childHasMore = true;
  private parentIsSearching = false;
  private childIsSearching = false;
  private parentSearchTerm = '';
  private childSearchTerm = '';
  private parentResults: any[] = [];
  private childResults: any[] = [];

  public isLoading$ = this.loaderService.isLoading$;


  /**
   * Determines if the object can act as both parent and child.
   */
  public isBidirectional = computed(() =>
    this.parentTypeIDs.includes(this.currentObjectTypeID) &&
    this.childTypeIDs.includes(this.currentObjectTypeID)
  );

  constructor(
    private fb: FormBuilder,
    private objectService: ObjectService,
    private toastService: ToastService,
    private objectRelationService: ObjectRelationService,
    private userService: UserService,
    private cdr: ChangeDetectorRef,
    private loaderService: LoaderService,
    private objectSearchFilterService: ObjectSearchFilterService) {
    this.form = this.fb.group({
      parent: [null],
      child: [null]
    });
    this.relationForm = this.fb.group({});
    this.author_id = this.userService.getCurrentUser().public_id;
  }

  ngOnInit(): void {
    this.initializeForms();
    this.setupVisibility();
    this.setupSearch();
    this.loadOptions();
    this.cdr.detectChanges();
  }

  ngOnDestroy(): void {
    this.destroy$?.next();
    this.destroy$?.complete();
  }

  /**
   * Initializes the form and pre-fills values based on mode.
   */
  private initializeForms(): void {
    // Initialize relationForm with fields from relation definition
    this.relationForm = this.fb.group({});
    if (this.relation?.sections) {
      this.sections = this.relation.sections;
      this.relation.fields?.forEach(field => {
        this.relationForm.addControl(field.name, this.fb.control(''));
      });
    }

    // Pre-fill with relationInstance data if available
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
          } else {
            // console.warn(`[DEBUG] Field '${fv.name}' from instance not found in relation fields`);
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
   * Determines which sections should be visible based on bidirectionality.
   */
  private setupVisibility(): void {
    if (this.isBidirectional()) {
      this.showParentSection = this.chosenRole !== 'child';
      this.showChildSection = this.chosenRole !== 'parent';
      if (this.chosenRole === 'both') {
        this.form.get('parent')?.enable();
        this.form.get('child')?.enable();
      }
    } else {
      this.showParentSection = this.chosenRole === 'child';
      this.showChildSection = this.chosenRole === 'parent';
    }
  }

  /**
   * Loads available parent and child options based on visibility settings.
   */
  private loadOptions(): void {
    if (this.showParentSection) this.loadParentOptions(true, true);
    if (this.showChildSection) this.loadChildOptions(true, true);
  }

  private loadParentOptions(resetPagination: boolean = true, showGlobalLoading: boolean = false): void {
    const validTypeIDs = this.validateTypeIDs(this.parentTypeIDs);
    if (!validTypeIDs.length) {
      this.toastService.warning('No valid parent type configuration');
      if (showGlobalLoading) {
        this.finishInitialLoad();
        this.cdr.detectChanges();
      }
      return;
    }

    if (resetPagination) {
      this.parentPage = 1;
      this.parentHasMore = true;
      this.parentResults = [];
    }

    if (showGlobalLoading) {
      this.startInitialLoad();
    }

    this.setSectionLoading('parent', true);
    this.cdr.detectChanges();

    const params: CollectionParameters = {
      filter: this.objectSearchFilterService.buildSearchPipeline(
        this.parentIsSearching ? this.parentSearchTerm : '',
        validTypeIDs
      ),
      projection: {
        'object_information.object_id': 1,
        'object_information.public_id': 1,
        'summary_line': 1,
        'type_information': 1,
        'type_id': 1
      },
      limit: this.parentIsSearching ? 0 : this.pageSize,
      sort: 'public_id',
      order: 1,
      page: this.parentIsSearching ? 1 : this.parentPage
    };

    this.objectService.getObjects(params)
      .pipe(takeUntil(this.destroy$), finalize(() => {
        this.setSectionLoading('parent', false);
        if (showGlobalLoading) {
          this.finishInitialLoad();
        }
        this.cdr.detectChanges();
      }))
      .subscribe({
        next: (response: APIGetMultiResponse<any>) => {
          const results = response?.results || [];
          const filtered = results.filter(obj => this.getObjectID(obj) !== this.currentObjectID);

          this.parentResults = this.mergeUniqueById(this.parentResults, filtered, resetPagination);
          this.flatParentOptions = this.buildFlatOptions(this.parentResults);

          if (!this.parentIsSearching) {
            this.parentHasMore = results.length === this.pageSize;
            this.parentPage = resetPagination ? 2 : this.parentPage + 1;
          }

          this.refreshOpenSelect('parent');
          this.cdr.detectChanges();
        },
        error: err => {
          this.toastService.error(err?.error?.message);
          this.cdr.detectChanges();
        }
      });
  }

  private loadChildOptions(resetPagination: boolean = true, showGlobalLoading: boolean = false): void {
    const validTypeIDs = this.validateTypeIDs(this.childTypeIDs);
    if (!validTypeIDs.length) {
      this.toastService.warning('No valid child type configuration');
      if (showGlobalLoading) {
        this.finishInitialLoad();
        this.cdr.detectChanges();
      }
      return;
    }

    if (resetPagination) {
      this.childPage = 1;
      this.childHasMore = true;
      this.childResults = [];
    }

    if (showGlobalLoading) {
      this.startInitialLoad();
    }

    this.setSectionLoading('child', true);
    this.cdr.detectChanges();

    const params: CollectionParameters = {
      filter: this.objectSearchFilterService.buildSearchPipeline(
        this.childIsSearching ? this.childSearchTerm : '',
        validTypeIDs
      ),
      projection: {
        'object_information.object_id': 1,
        'object_information.public_id': 1,
        'summary_line': 1,
        'type_information': 1,
        'type_id': 1
      },
      limit: this.childIsSearching ? 0 : this.pageSize,
      sort: 'public_id',
      order: 1,
      page: this.childIsSearching ? 1 : this.childPage
    };

    this.objectService.getObjects(params)
      .pipe(takeUntil(this.destroy$), finalize(() => {
        this.setSectionLoading('child', false);
        if (showGlobalLoading) {
          this.finishInitialLoad();
        }
        this.cdr.detectChanges();
      }))
      .subscribe({
        next: (response: APIGetMultiResponse<any>) => {
          const results = response?.results || [];
          const filtered = results.filter(obj => this.getObjectID(obj) !== this.currentObjectID);

          this.childResults = this.mergeUniqueById(this.childResults, filtered, resetPagination);
          this.flatChildOptions = this.buildFlatOptions(this.childResults);

          if (!this.childIsSearching) {
            this.childHasMore = results.length === this.pageSize;
            this.childPage = resetPagination ? 2 : this.childPage + 1;
          }

          this.refreshOpenSelect('child');
          this.cdr.detectChanges();
        },
        error: err => {
          this.toastService.error(err?.error?.message);
          this.cdr.detectChanges();
        }
      });
  }



  public noCounterpartOptions(): boolean {
    if (this.isBidirectional()) {
      return (this.showParentSection && this.flatChildOptions.length === 0) &&
        (this.showChildSection && this.flatParentOptions.length === 0);
    }
    return this.chosenRole === 'parent'
      ? this.flatChildOptions.length === 0
      : this.flatParentOptions.length === 0;
  }

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

    let parentTypeID = this.currentObjectTypeID;
    let childTypeID = this.currentObjectTypeID;

    if (this.form.value.parent) {
      const selectedParent = this.flatParentOptions.find(opt => opt.value === this.form.value.parent);
      parentTypeID = selectedParent ? this.parseTypeIdFromGroup(selectedParent.group) : parentTypeID;
    }

    if (this.form.value.child) {
      const selectedChild = this.flatChildOptions.find(opt => opt.value === this.form.value.child);
      childTypeID = selectedChild ? this.parseTypeIdFromGroup(selectedChild.group) : childTypeID;
    }

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
      this.objectRelationService.putObjectRelation(this.relationInstance.public_id, dto).pipe( finalize(() => this.loaderService.hide())).subscribe({
        next: (res) => {
          this.toastService.success(`Relation updated successfully`);
          this.onConfirm.emit({
            parentObjID,
            childObjID,
            relationData: res
          });
        },
        error: (err) => {
          this.toastService.error(err?.error?.message);
        }
      });
    } else {
      this.loaderService.show();
      this.objectRelationService.postObjectRelation(dto).pipe( finalize(() => this.loaderService.hide())).subscribe({
        next: (res) => {
          this.toastService.success(`Relation created successfully`);
          this.onConfirm.emit({
            parentObjID,
            childObjID,
            relationData: res
          });
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
    if (this.loading || this.mode === CmdbMode.View) {
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

  /* ------------------------------------------------ SEARCH & PAGINATION ------------------------------------------------ */

  private setupSearch(): void {
    this.parentSearchSubject.pipe(
      debounceTime(800),
      distinctUntilChanged(),
      takeUntil(this.destroy$)
    ).subscribe(term => this.handleParentSearch(term));

    this.childSearchSubject.pipe(
      debounceTime(800),
      distinctUntilChanged(),
      takeUntil(this.destroy$)
    ).subscribe(term => this.handleChildSearch(term));
  }

  public onParentScrollToEnd(): void {
    if (!this.parentIsSearching && this.parentHasMore && !this.parentIsLoading) {
      this.loadParentOptions(false);
    }
  }

  public onChildScrollToEnd(): void {
    if (!this.childIsSearching && this.childHasMore && !this.childIsLoading) {
      this.loadChildOptions(false);
    }
  }

  public onParentSearch(searchTerm: string): void {
    this.parentSearchSubject.next(searchTerm);
  }

  public onChildSearch(searchTerm: string): void {
    this.childSearchSubject.next(searchTerm);
  }

  private handleParentSearch(searchTerm: string): void {
    this.parentSearchTerm = searchTerm || '';
    this.parentIsSearching = !!this.parentSearchTerm;
    this.loadParentOptions(true);
  }

  private handleChildSearch(searchTerm: string): void {
    this.childSearchTerm = searchTerm || '';
    this.childIsSearching = !!this.childSearchTerm;
    this.loadChildOptions(true);
  }


  /* ------------------------------------------------ HELPER FUNCTIONS ------------------------------------------------ */

  /**
   * Validates and extracts type IDs, ensuring they are positive integers.
   * @param ids - The array of IDs to validate.
   * @returns An array of valid type IDs.
   */
  private validateTypeIDs(ids: any[]): number[] {
    return ids.flat(Infinity).filter((id: any) => Number.isInteger(id) && id > 0);
  }

  /**
   * Builds a list of formatted options from object results.
   * @param results - The array of objects to process.
   * @returns An array of flat option items.
   */
  private buildFlatOptions(results: any[]): FlatOptionItem[] {
    if (!Array.isArray(results) || results.length === 0) return [];
    const typeMap: Record<number, { label: string; count: number }> = {};

    for (const obj of results) {
      const tId = this.getTypeID(obj);
      const tLabel = this.getTypeLabel(obj);
      typeMap[tId] = typeMap[tId] || { label: tLabel, count: 0 };
      typeMap[tId].count++;
    }

    return results.map(obj => {
      const tId = this.getTypeID(obj);
      const groupLabel = `${typeMap[tId].label} [${tId}]`;
      const objectId = this.getObjectID(obj);
      const summary = this.getSummary(obj);

      return {
        value: objectId,
        label: summary ? `${typeMap[tId].label} #${objectId} ${summary}` : `${typeMap[tId].label} #${objectId}`,
        group: groupLabel
      };
    }).sort((a, b) => a.group.localeCompare(b.group));
  }

  /* ------------------------------------------------ GETTERS------------------------------------------------ */

  /**
   * Retrieves a field object by name from the relation definition.
   * @param fieldName - The name of the field to retrieve.
   * @returns The field object if found, otherwise undefined.
   */
  public getFieldObject(fieldName: string) {
    return this.relation?.fields?.find(f => f.name === fieldName);
  }

  /**
   * Extracts the type ID from a formatted group label.
   * @param groupStr - The group string containing the type ID.
   * @returns The parsed type ID or 0 if not found.
   */
  private parseTypeIdFromGroup(groupStr: string): number {
    const match = groupStr.match(/\[(\d+)\]/);
    return match ? parseInt(match[1], 10) : 0;
  }

  /**
   * Retrieves the type ID of an object.
   * @param obj - The object to extract the type ID from.
   * @returns The type ID or 0 if not found.
   */
  private getTypeID(obj: any): number {
    return obj?.type_information?.type_id ?? obj?.type_id ?? 0;
  }

  /**
   * Retrieves the object ID from an object.
   * @param obj - The object to extract the ID from.
   * @returns The object ID or 0 if not found.
   */
  private getObjectID(obj: any): number {
    return obj?.object_information?.object_id ?? obj?.public_id ?? 0;
  }

  /**
   * Retrieves the summary of an object.
   * @param obj - The object to extract the summary from.
   * @returns The summary string or an empty string if not found.
   */
  private getSummary(obj: any): string {
    return obj?.summary_line ?? '';
  }

  /**
   * Retrieves the type label of an object.
   * @param obj - The object to extract the label from.
   * @returns The type label or a default label if not found.
   */
  private getTypeLabel(obj: any): string {
    return obj?.type_information?.type_label ?? ('Type ' + (obj?.type_id ?? 'Unknown'));
  }

  /**
   * Determines the current view mode.
   * @returns The current mode (View or Edit).
   */
  public getViewMode(): CmdbMode {
    return this.mode === CmdbMode.View ? CmdbMode.View : CmdbMode.Edit;
  }

  public get parentHasMoreData(): boolean {
    return this.parentHasMore;
  }

  public get childHasMoreData(): boolean {
    return this.childHasMore;
  }

  private setSectionLoading(section: 'parent' | 'child', isLoading: boolean): void {
    if (section === 'parent') {
      this.parentIsLoading = isLoading;
    } else {
      this.childIsLoading = isLoading;
    }
  }

  private startInitialLoad(): void {
    this.initialLoadCount++;
    this.loading = true;
    this.cdr.detectChanges();
  }

  private finishInitialLoad(): void {
    this.initialLoadCount = Math.max(0, this.initialLoadCount - 1);
    if (this.initialLoadCount === 0) {
      this.loading = false;
    }
    this.cdr.detectChanges();
  }

  private mergeUniqueById(existing: any[], incoming: any[], reset: boolean): any[] {
    if (reset) {
      return this.uniqueById(incoming);
    }
    return this.uniqueById([...existing, ...incoming]);
  }

  private uniqueById(items: any[]): any[] {
    const seen = new Set<number>();
    const result: any[] = [];
    for (const item of items) {
      const id = this.getObjectID(item);
      if (!seen.has(id)) {
        seen.add(id);
        result.push(item);
      }
    }
    return result;
  }

  private refreshOpenSelect(section: 'parent' | 'child'): void {
    const select = section === 'parent' ? this.parentSelect : this.childSelect;
    if (select?.isOpen) {
      const items = section === 'parent' ? this.flatParentOptions : this.flatChildOptions;
      if (select.itemsList?.setItems) {
        select.itemsList.setItems(items);
        if (select.searchTerm) {
          select.itemsList.filter(select.searchTerm);
        }
        if (select.itemsList.markSelectedOrDefault) {
          select.itemsList.markSelectedOrDefault(select.markFirst);
        }
      }
      select.detectChanges?.();
      select.dropdownPanel?.adjustPosition?.();
    }
  }

} 
