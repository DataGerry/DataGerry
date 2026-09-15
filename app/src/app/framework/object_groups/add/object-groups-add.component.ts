import { Component, inject, OnInit } from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import { finalize } from 'rxjs/operators';
import { Observable } from 'rxjs';

import { ToastService } from 'src/app/layout/toast/toast.service';
import { LoaderService } from 'src/app/core/services/loader.service';

import { CmdbType } from 'src/app/framework/models/cmdb-type';
import { ExtendableOptionService } from 'src/app/toolbox/isms/services/extendable-option.service';
import { ObjectGroupService } from '../../services/object-group.service';
import { TypeService } from '../../services/type.service';

import { ObjectGroup, ObjectGroupMode, ExtendableOption } from '../../models/object-group.model';
import { OptionType } from 'src/app/toolbox/isms/models/option-type.enum';
import { NgbModal } from '@ng-bootstrap/ng-bootstrap';
import { ExtendableOptionManagerComponent } from 'src/app/core/components/extendable_option_manager/extendable-option-manager.component';

interface SelectOption {
  value: number;
  label: string;
}

@Component({
    selector: 'app-object-groups-add',
    templateUrl: './object-groups-add.component.html',
    styleUrls: ['./object-groups-add.component.scss'],
    standalone: false
})
export class ObjectGroupsAddComponent implements OnInit {
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly toast = inject(ToastService);
  private readonly loaderService = inject(LoaderService);
  private readonly objectGroupService = inject(ObjectGroupService);
  private readonly extendableOptionService = inject(ExtendableOptionService);
  private readonly typeService = inject(TypeService);
  private readonly modalService = inject(NgbModal);

  public isEditMode = false;
  public isViewMode = false;
  public groupId?: number;
  public isLoading$ = this.loaderService.isLoading$;

  // Model for creating / editing an object group
  public group: ObjectGroup = {
    name: '',
    group_type: ObjectGroupMode.STATIC,
    categories: [],
    assigned_ids: []
  };

  // Category options for the main form
  public categoryOptions: ExtendableOption[] = [];

  // Track previous group type to handle changes
  private previousGroupType?: string;

  // Cache types for dynamic selection
  private static allTypes: CmdbType[] | null = null;
  public typeOptions: SelectOption[] = [];
  public allTypeIds: number[] = [];
  public typesLoaded = false;

  ngOnInit(): void {
    const state = history.state;
    this.groupId = +this.route.snapshot.paramMap.get('id');
    // The route decides the mode so a deep link to /view/:id can never open an editable form
    this.isViewMode = this.route.snapshot.data?.['isViewMode'] === true;
    this.isEditMode = !!this.groupId && !this.isViewMode;


    if (state?.group) {
      this.group = { ...state.group };
    }

    // Always load categories & types
    this.loadCategories();
    this.loadTypesIfNeeded();

    // Only call API if data not passed (fallback)
    if (!state?.group && this.groupId) {
      this.loadGroupToEdit(this.groupId);
    }

    this.previousGroupType = this.group.group_type;
  }


  /* --------------------------- Categories --------------------------- */

  private loadCategories(): void {
    this.extendableOptionService.getExtendableOptionsByType(OptionType.OBJECT_GROUP)
      .subscribe({
        next: (res) => {
          this.categoryOptions = res.results;
        },
        error: (err) => this.toast.error(err?.error?.message)
      });
  }

  /* --------------------------- Editing a single group --------------------------- */

  private loadGroupToEdit(id: number): void {
    this.loaderService.show();
    this.objectGroupService.getObjectGroupById(id)
      .pipe(finalize(() => this.loaderService.hide()))
      .subscribe({
        next: (resp) => {
          // 'resp' is type APIGetSingleResponse<ObjectGroup>
          const item = resp.result;

          // use 'item' as an ObjectGroup
          this.group = {
            public_id: item.public_id,
            name: item.name,
            group_type: item.group_type,
            categories: item.categories,
            assigned_ids: item.assigned_ids,
          };

        },
        error: (err) => {
          this.toast.error(err?.error?.message);
          this.router.navigate(['/framework/object_groups']);
        }
      });

  }

  /* --------------------------- Type Options (STATIC / DYNAMIC) --------------------------- */

  private loadTypesIfNeeded(): void {
    if (ObjectGroupsAddComponent.allTypes && ObjectGroupsAddComponent.allTypes.length > 0) {
      this.typeOptions = this.buildTypeOptions(ObjectGroupsAddComponent.allTypes);
      this.allTypeIds = ObjectGroupsAddComponent.allTypes.map(t => t.public_id);
      this.typesLoaded = true;
      return;
    }

    this.loaderService.show();

    const params = {
      filter:
        (this.isViewMode &&
          this.group.group_type === ObjectGroupMode.DYNAMIC &&
          Array.isArray(this.group.assigned_ids) &&
          this.group.assigned_ids.length > 0)
          ? { public_id: { $in: this.group.assigned_ids } }
          : '',
      limit: 0,
      sort: 'sort',
      order: 1,
      page: 1,
      projection: ['public_id', 'label', 'name'],
    };

    this.typeService.getTypes(params)
      .pipe(finalize(() => this.loaderService.hide()))
      .subscribe({
        next: (resp) => {
          const types = resp.results as CmdbType[];
          ObjectGroupsAddComponent.allTypes = types;
          this.typeOptions = this.buildTypeOptions(types);
          this.allTypeIds = types.map(t => t.public_id);
          this.typesLoaded = true;
        },
        error: (err) => this.toast.error(err?.error?.message)
      });
  }

  private buildTypeOptions(types: CmdbType[]): SelectOption[] {
    return types.map(t => ({
      value: t.public_id,
      label: t.label || t.name || `Type #${t.public_id}`
    }));
  }

  /**
   * Called when the user manually changes the group type radio.
   * We no longer reset assigned_ids here, so that editing an existing group
   * will show the previously saved objects or type IDs.
   */
  public onGroupTypeChange(): void {
    if (this.group.group_type !== this.previousGroupType) {
      this.group.assigned_ids = [];
      this.previousGroupType = this.group.group_type;
    }
  }

  /** Handler for object selector's selection change (STATIC case) */
  public onObjectsSelected(selectedIds: number[]): void {
    this.group.assigned_ids = selectedIds;
  }

  /* --------------------------- Save / Cancel --------------------------- */

  public onSave(): void {
    this.loaderService.show();
    let request$: Observable<any>;

    // Switch between update / create
    if (this.isEditMode && this.group.public_id) {
      request$ = this.objectGroupService.updateObjectGroup(this.group.public_id, this.group) as Observable<any>;
    } else {
      request$ = this.objectGroupService.createObjectGroup(this.group) as Observable<any>;
    }

    request$
      .pipe(finalize(() => this.loaderService.hide()))
      .subscribe({
        next: () => {
          this.toast.success(`Object Group ${this.isEditMode ? 'updated' : 'created'} successfully`);
          this.router.navigate(['/framework/object_groups']);
        },
        error: (err) => {
          this.toast.error(err?.error?.message);
        }
      });
  }

  public onCancel(): void {
    this.router.navigate(['/framework/object_groups']);
  }

  /* ---------------------- Category Manager ---------------------- */

  public openCategoryManager(): void {
    const modalRef = this.modalService.open(ExtendableOptionManagerComponent, {
      size: 'lg',
      windowClass: 'dg-modal-window',
      backdropClass: 'dg-modal-window-backdrop'
    });

    modalRef.componentInstance.options = this.categoryOptions;
    modalRef.componentInstance.optionType = OptionType.OBJECT_GROUP;
    modalRef.componentInstance.modalTitle = 'Manage Categories';
    modalRef.componentInstance.itemLabel = 'Category';
    modalRef.componentInstance.itemLabelPlural = 'Categories';

    // Refresh main category list after closing
    modalRef.result.then(() => this.loadCategories(), () => this.loadCategories());
  }

  /* ---------------------- Validation Helpers ---------------------- */

  public isSaveDisabled(): boolean {
    if (
      (!this.group.assigned_ids || this.group.assigned_ids.length === 0)
    ) {
      return true;
    }
    return false;
  }
}