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
import {
  AfterViewInit,
  ChangeDetectionStrategy,
  ChangeDetectorRef,
  Component,
  HostListener,
  OnDestroy,
  OnInit,
  TemplateRef,
  ViewChild
} from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import { BehaviorSubject, Subject, takeUntil, forkJoin, switchMap, map, finalize } from 'rxjs';
import { CmdbMode } from 'src/app/framework/modes.enum';
import { ObjectService } from 'src/app/framework/services/object.service';
import { ObjectRelationService } from 'src/app/framework/services/object-relation.service';
import { TypeService } from 'src/app/framework/services/type.service';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { RenderResult } from 'src/app/framework/models/cmdb-render';
import { CmdbRelation } from 'src/app/framework/models/relation.model';
import { RelationService } from '../../services/relaion.service';
import { NgbModal } from '@ng-bootstrap/ng-bootstrap';
import { CoreDeleteConfirmationModalComponent } from 'src/app/core/components/dialog/delete-dialog/core-delete-confirmation-modal.component';
import { CmdbObject } from '../../models/cmdb-object';
import { ExtendedRelation, RelationGroup, ExtendedObjectRelationInstance, ObjectRelationInstance } from '../../models/object.model';
import { LoaderService } from 'src/app/core/services/loader.service';



@Component({
    selector: 'cmdb-object-view',
    templateUrl: './object-view.component.html',
    styleUrls: ['./object-view.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    standalone: false
})
export class ObjectViewComponent implements OnInit, OnDestroy, AfterViewInit {

  /* --------------------------------------------------- MEMBER FIELDS -------------------------------------------------- */

  // Table templates
  @ViewChild('counterpartIdTemplate', { static: true }) counterpartIdTemplate: TemplateRef<any>;
  @ViewChild('actionsTemplate', { static: true }) actionsTemplate: TemplateRef<any>;
  @ViewChild('counterpartTypeTemplate', { static: true }) counterpartTypeTemplate: TemplateRef<any>;

  public mode: CmdbMode = CmdbMode.View;
  public renderResult: RenderResult;
  public currentObjectID: number;
  private unsubscribe = new Subject<void>();
  private objectViewSubject = new BehaviorSubject<RenderResult>(undefined);

  // Modal and loading states
  public showRelationModal = false;
  public loadingRelations = false;
  public showRelationRoleDialog = false;
  isGraphView: boolean = false;


  // Relation selection
  public availableRelations: CmdbRelation[] = [];
  public extendedRelations: ExtendedRelation[] = [];
  public chosenRelation: ExtendedRelation = null;
  public chosenRole: 'parent' | 'child' = null;
  public roleParentTypeIDs: number[] = [];
  public roleChildTypeIDs: number[] = [];

  // Tab management
  public relationGroups: RelationGroup[] = [];
  public activeRelationTabIndex = 0;
  public activeNestedRelationTabIndex = 0; // Tracks the active tab within Object Relations

  private currentActiveRelationTabIndex: number = 0;
  private shouldPreserveTabState: boolean = false;

  // Action properties
  public dialogMode: CmdbMode = CmdbMode.Create;
  public selectedRelationInstance: ExtendedObjectRelationInstance | null = null;
  public isHeaderSelectorLoading = false;

  // Tracks whether a relation is already used as parent/child by this object
  private usedRolesMap = new Map<number, { parentUsed: boolean; childUsed: boolean }>();

  // Summaries of related objects
  private relatedObjectsMap: { [id: number]: RenderResult | CmdbObject } = {};

  // Pagination & Sorting
  public totalRelations: number = 0;
  public relationPage: number = 1;
  public relationPageSize: number = 10;
  public relationSort: string = '';
  public relationOrder: number = 1;

  public isLoading$ = this.loaderService.isLoading$;

  // Selector for Graph header
  public allTypeIds: number[] = [];
  public typesLoaded: boolean = false;
  public selectedObjectIdForSelector: number | null = null;
  private pendingSelectedId: number | null = null;

  /* --------------------------------------------------- LIFECYCLE METHODS -------------------------------------------------- */

  constructor(
    public objectService: ObjectService,
    private relationService: RelationService,
    private objectRelationService: ObjectRelationService,
    public typeService: TypeService,
    private activateRoute: ActivatedRoute,
    private toastService: ToastService,
    private changesRef: ChangeDetectorRef,
    private modalService: NgbModal,
    private loaderService: LoaderService,
    private router: Router
  ) {
    this.activateRoute.data.subscribe({
      next: (data: any) => this.objectViewSubject.next(data.object as RenderResult),
      error: (err) => this.toastService.error(err?.error?.message)
    });
  }

  ngOnInit(): void {

    // Auto-switch to graph view when query param view=graph
    this.activateRoute.queryParamMap
      .pipe(takeUntil(this.unsubscribe))
      .subscribe(params => {
        const view = params.get('view');
        if (view === 'graph') this.isGraphView = true;
      });

    this.objectViewSubject.pipe(takeUntil(this.unsubscribe)).subscribe({
      next: (result) => {
        this.renderResult = result;

        this.currentObjectID = result?.object_information?.object_id;
        this.activeRelationTabIndex = 0;
        if (this.currentObjectID) {
          this.loadObjectRelationInstances(this.currentObjectID);
        }
        this.changesRef.markForCheck();
      },
      error: (e) => this.toastService.error(e?.error?.message)
    });

    // Load all type IDs for object selector
    const params = { filter: '', limit: 0, sort: 'public_id', order: 1, page: 1 } as any;
    this.typeService.getTypes(params)
      .pipe(takeUntil(this.unsubscribe), finalize(() => this.changesRef.markForCheck()))
      .subscribe({
        next: (resp: any) => {
          this.allTypeIds = (resp?.results || []).map((t: any) => t.public_id);
          this.typesLoaded = true;
        },
        error: () => {
          this.typesLoaded = true;
        }
      });
  }

  ngAfterViewInit(): void {
    this.changesRef.detectChanges();
  }

  ngOnDestroy(): void {
    this.unsubscribe?.next();
    this.unsubscribe?.complete();
  }

  @HostListener('window:scroll')
  onWindowScroll(): void {
    const dialog = document.getElementsByClassName('object-view-navbar') as HTMLCollectionOf<Element>;
    if (!dialog[0]) return;
    dialog[0].id = document.body.scrollTop > 20 ? 'object-form-action' : '';
    dialog[0].classList.toggle('shadow', document.body.scrollTop > 20);
  }

  /* --------------------------------------------------- UI / EVENT HANDLERS -------------------------------------------------- */

  /** Sets the active tab index */
  public setActiveTab(tabIndex: number): void {
    this.activeRelationTabIndex = tabIndex;
    if (tabIndex !== 1) {
      this.activeNestedRelationTabIndex = 0; // Reset nested tab when switching away from Object Relations
    }

    if (tabIndex > 0) {
      const groupIndex = tabIndex - 1;
      const group = this.relationGroups[groupIndex];
      // if there are more than 10 items in the a rel table then execute this for the pagination stuff
      group?.total > 10 ? this.loadGroupInstances(group?.relationId, group?.isParent, 1, 10) : null
    }
    this.changesRef.markForCheck();
  }


  /** Handles clicking the "+" tab to add a new relation */
  public onClickAddRelationTab(): void {
    this.openRelationModal();
    this.setActiveTab(1); // Ensure Object Relations is active
    this.setNestedRelationTab(this.relationGroups.length); // Highlight the "+" tab
  }


  /**
 * Creates a new relation for an existing relation group.
 * @param group The relation group to create a new instance for
 */
  public createNewRelationForGroup(group: RelationGroup): void {
    // Try to get the definition from the first instance in the group.
    // let definition = group?.instances.length > 0 ? group?.instances[0]?.definition : null;
    // TODO: undo it because of inactive relations
    let definition = group.instances[0]?.definition ?? (group as any).definition;

    // If not found, look for the definition in extendedRelations.
    if (!definition) {
      definition = this.extendedRelations.find(rel => rel?.public_id === group?.relationId);
    }
    if (!definition) {
      this.toastService.error('Relation definition is missing.');
      return;
    }

    const safeDefinition = {
      ...definition,
      parent_type_ids: Array.isArray(definition?.parent_type_ids) ? definition?.parent_type_ids : [],
      child_type_ids: Array.isArray(definition?.child_type_ids) ? definition?.child_type_ids : [],
      canBeParent: group.isParent,
      canBeChild: !group?.isParent
    };

    this.chosenRelation = safeDefinition;
    this.chosenRole = group?.isParent ? 'parent' : 'child';
    this.roleParentTypeIDs = this.chosenRole === 'parent' ? [] : safeDefinition?.parent_type_ids;
    this.roleChildTypeIDs = this.chosenRole === 'child' ? [] : safeDefinition?.child_type_ids;

    if (this.chosenRole === 'parent' && this.roleChildTypeIDs.length === 0) {
      this.toastService.warning('No child types defined for this relation.');
      return;
    }
    if (this.chosenRole === 'child' && this.roleParentTypeIDs.length === 0) {
      this.toastService.warning('No parent types defined for this relation.');
      return;
    }

    // Preserve the current tab state
    this.currentActiveRelationTabIndex = this.activeRelationTabIndex;
    this.shouldPreserveTabState = true;

    this.showRelationRoleDialog = true;
    this.dialogMode = CmdbMode.Create; // Set mode to Create
    this.selectedRelationInstance = null; // Clear any selected instance
    this.changesRef.markForCheck();
  }

  private setChosenRelationAndRole(
    instance: ExtendedObjectRelationInstance,
    mode: CmdbMode
  ): void {
    // 1) Mark which side is parent/child
    const isParent = instance?.relation_parent_id === this.currentObjectID;

    // 2) Build the final definition
    const definition = instance?.definition || {} as CmdbRelation;
    this.chosenRelation = {
      ...definition,
      canBeParent: isParent,
      canBeChild: !isParent
    };

    // 3) Set chosenRole accordingly
    this.chosenRole = isParent ? 'parent' : 'child';

    // 4) Parent/Child type IDs
    this.roleParentTypeIDs = this.chosenRole === 'parent' ? [] : definition?.parent_type_ids || [];
    this.roleChildTypeIDs = this.chosenRole === 'child' ? [] : definition?.child_type_ids || [];

    // 5) Mode and selected instance
    this.dialogMode = mode;
    this.selectedRelationInstance = instance;
  }

  public viewRelationInstance(instance: ExtendedObjectRelationInstance): void {
    this.setChosenRelationAndRole(instance, CmdbMode.View);
    this.showRelationRoleDialog = true;
    this.changesRef.detectChanges();
  }

  public editRelationInstance(instance: ExtendedObjectRelationInstance): void {
    this.setChosenRelationAndRole(instance, CmdbMode.Edit);
    this.showRelationRoleDialog = true;
    this.changesRef.detectChanges();
  }

  public copyRelationInstance(instance: ExtendedObjectRelationInstance): void {
    this.setChosenRelationAndRole(instance, CmdbMode.Create);
    this.showRelationRoleDialog = true;
    this.changesRef.detectChanges();
  }



  /**
  * Deletes a relation instance using a reusable core delete modal.
  * @param instance The relation instance to delete.
  */
  public deleteRelationInstance(instance: ExtendedObjectRelationInstance): void {
    const modalRef = this.modalService.open(CoreDeleteConfirmationModalComponent, { size: 'lg' });
    modalRef.componentInstance.title = 'Delete Object Relation';
    modalRef.componentInstance.item = instance;
    modalRef.componentInstance.itemType = 'Object Relation';
    modalRef.componentInstance.itemName = instance?.public_id;

    // Check if this is the last instance in the group
    const group = this.relationGroups.find(
      g => g?.relationId === instance?.relation_id &&
        g?.isParent === (instance.relation_parent_id === this.currentObjectID)
    );
    const isLastInstanceInGroup = group?.instances?.length === 1;

    modalRef.result.then(
      (result) => {
        if (result === 'confirmed') {
          this.loadingRelations = true;
          this.objectRelationService?.deleteObjectRelation(instance?.public_id)
            .pipe(takeUntil(this.unsubscribe))
            .subscribe({
              next: () => {
                this.toastService.success('Relation instance deleted successfully');
                this.loadObjectRelationInstances(this.currentObjectID);
                if (isLastInstanceInGroup) {
                  this.loadRelationsForNewRelation();
                }
              },
              error: (err) => {
                this.toastService.error(err?.error?.message);
                this.loadingRelations = false;
                this.changesRef.markForCheck();
              }
            });
        }
      },
      () => { }
    );
  }


  /**
   * Opens the relation selection modal 
   */
  public openRelationModal(): void {
    // Refresh used relations and available relations.
    this.loadObjectRelationInstances(this.currentObjectID);
    this.loadRelationsForNewRelation();

    // Reset current selection.
    this.chosenRelation = null;
    this.chosenRole = null;

    setTimeout(() => {
      this.showRelationModal = true;
      this.changesRef.detectChanges();
    }, 10);
  }


  /** Closes the relation selection modal */
  public closeRelationModal(): void {
    this.showRelationModal = false;
  }


  /** Selects a relation and role in the modal */
  public onSelectRelation(relation: ExtendedRelation, role: 'parent' | 'child'): void {
    if ((role === 'parent' && !relation?.canBeParent) || (role === 'child' && !relation?.canBeChild)) {
      return;
    }
    this.chosenRelation = relation;
    this.chosenRole = role;
  }


  /** Confirms relation selection and opens role dialog */
  public onConfirmRelationSelection(): void {
    if (!this.chosenRelation || !this.chosenRole) return;
    this.closeRelationModal();
    this.roleParentTypeIDs = this.chosenRole === 'parent' ? [] : this.chosenRelation?.parent_type_ids;
    this.roleChildTypeIDs = this.chosenRole === 'child' ? [] : this.chosenRelation?.child_type_ids;

    this.currentActiveRelationTabIndex = this.activeRelationTabIndex;
    this.shouldPreserveTabState = true;

    this.showRelationRoleDialog = true;
    this.dialogMode = CmdbMode.Create; // Ensure Create mode for new relations
    this.selectedRelationInstance = null; // Clear any selected instance
    this.changesRef.detectChanges();
  }


  /** Handles confirmation from the relation role dialog */
  public onRelationRoleDialogConfirm(selection: { parentObjID?: number; childObjID?: number }): void {
    this.showRelationRoleDialog = false;
    this.selectedRelationInstance = null;
    this.dialogMode = CmdbMode.Create; // Reset to default mode

    this.currentActiveRelationTabIndex = this.activeRelationTabIndex;
    this.shouldPreserveTabState = true;
    if (this.currentObjectID) {
      this.loadObjectRelationInstances(this.currentObjectID);
    }
    this.changesRef.markForCheck();
  }


  /** Handles cancellation from the relation role dialog */
  public onRelationRoleDialogCancel(): void {
    this.showRelationRoleDialog = false;
    this.selectedRelationInstance = null;
    this.dialogMode = CmdbMode.Create; // Reset to default mode
    this.toastService.info('Operation cancelled');
    this.changesRef.markForCheck();
  }


  // Table changes
  public onRelationPageChange(newPage: number): void {
    this.relationPage = newPage;
    this.loadObjectRelationInstances(this.currentObjectID);
  }


  public onRelationPageSizeChange(newLimit: number): void {
    this.relationPageSize = newLimit;
    this.relationPage = 1; // Reset to first page
    this.loadObjectRelationInstances(this.currentObjectID);
  }


  public onRelationSortChange(event: { sort: string; order: number }): void {
    this.relationSort = event?.sort;
    this.relationOrder = event?.order;
    this.loadObjectRelationInstances(this.currentObjectID);
  }


  public onRelationSearchChange(searchTerm: string): void {
    this.loadObjectRelationInstances(this.currentObjectID);
  }


  /* --------------------------------------------------- API / DATA METHODS -------------------------------------------------- */

  /**
* Loads and groups object relation instances by relation type and role.
* @param objectID The ID of the current object
*/
  private loadObjectRelationInstances(objectID: number): void {

    if (!objectID) {
      this.toastService.error('Invalid object ID');
      return;
    }

    this.loaderService.show();

    const params = {
      filter: {
        $or: [
          { relation_parent_id: objectID },
          { relation_child_id: objectID }
        ]
      },
      limit: 0,
      sort: this.relationSort,
      order: this.relationOrder,
      page: this.relationPage
    };

    this.loadingRelations = true;
    this.objectRelationService.getObjectRelations(params)
      .pipe(takeUntil(this.unsubscribe), finalize(() => this.loaderService?.hide()))
      .subscribe({
        next: (response) => {
          this.totalRelations = response.total;
          const relationInstances: ObjectRelationInstance[] = response?.results || [];
          if (!relationInstances.length) {
            this.relationGroups = [];
            this.loadingRelations = false;
            this.changesRef.markForCheck();
            return;
          }

          this.usedRolesMap = new Map<number, { parentUsed: boolean; childUsed: boolean }>();
          relationInstances.forEach(inst => {
            let roles = this.usedRolesMap.get(inst?.relation_id);
            if (!roles) {
              roles = { parentUsed: false, childUsed: false };
            }
            if (inst.relation_parent_id === this.currentObjectID) {
              roles.parentUsed = true;
            }
            if (inst.relation_child_id === this.currentObjectID) {
              roles.childUsed = true;
            }
            this.usedRolesMap.set(inst?.relation_id, roles);
          });

          const relationIds = [...new Set(relationInstances.map(inst => inst?.relation_id))];
          const relationObservables = relationIds.map(id => this.relationService.getRelation(id));
          const oldTabIndex = this.activeRelationTabIndex;

          forkJoin(relationObservables).pipe(takeUntil(this.unsubscribe)).subscribe({
            next: (definitions: CmdbRelation[]) => {
              const relationMap = new Map<number, CmdbRelation>();
              definitions.forEach(def => relationMap.set(def?.public_id, def));

              const groupedInstances = relationInstances.reduce((acc, instance) => {
                const key = instance?.relation_id;
                if (!acc[key]) acc[key] = [];
                acc[key].push(instance);
                return acc;
              }, {} as Record<number, ObjectRelationInstance[]>);

              const groups: RelationGroup[] = [];
              for (const relationIdStr in groupedInstances) {
                const relationId = parseInt(relationIdStr, 10);
                const instancesForRelation = groupedInstances[relationId];
                const definition = relationMap.get(relationId);
                if (!definition) {
                  continue;
                }

                const parentInstances = instancesForRelation
                  .filter(inst => inst.relation_parent_id === this.currentObjectID)
                  .map(inst => ({
                    ...inst,
                    counterpart_id: inst?.relation_child_id,
                    type: definition.relation_name_parent,
                    definition
                  }));

                const childInstances = instancesForRelation
                  .filter(inst => inst?.relation_child_id === this.currentObjectID)
                  .map(inst => ({
                    ...inst,
                    counterpart_id: inst?.relation_parent_id,
                    type: definition?.relation_name_child,
                    definition
                  }));

                if (parentInstances.length > 0) {
                  groups.push({
                    relationId,
                    isParent: true,
                    tabLabel: definition?.relation_name_parent,
                    tabColor: definition?.relation_color_parent,
                    tabIcon: definition?.relation_icon_parent,
                    instances: parentInstances,
                    total: parentInstances?.length,
                    // TODO: remove definition from here because it's hiding the inactive relations
                    definition
                  });
                }

                if (childInstances.length > 0) {
                  groups.push({
                    relationId,
                    isParent: false,
                    tabLabel: definition?.relation_name_child,
                    tabColor: definition?.relation_color_child,
                    tabIcon: definition?.relation_icon_child,
                    instances: childInstances,
                    total: childInstances.length,
                    // TODO: remove definition from here because it's hiding the inactive relations
                    definition
                  });
                }
              }

              this.relationGroups = groups;

              const allIDs: number[] = [];
              this.relationGroups?.forEach((g) => {
                g?.instances?.forEach((inst) => {
                  if (!allIDs?.includes(inst?.counterpart_id)) {
                    allIDs.push(inst?.counterpart_id);
                  }
                });
              });

              this.loadCounterpartObjects(allIDs);

              // if (this.activeRelationTabIndex === 1 && this.activeNestedRelationTabIndex > this.relationGroups.length) {
              //   this.activeNestedRelationTabIndex = 0;
              // } else if (oldTabIndex > 1) {
              //   this.activeRelationTabIndex = 1; // Move to Object Relations if previously on a relation tab
              //   this.activeNestedRelationTabIndex = oldTabIndex - 1; // Adjust for new structure
              // } else {
              //   this.activeRelationTabIndex = oldTabIndex;
              // }

              // Preserve tab state if needed, otherwise use existing logic
              if (this.shouldPreserveTabState) {
                this.activeRelationTabIndex = this.currentActiveRelationTabIndex;
                this.shouldPreserveTabState = false; // Reset the flag
              } else {
                if (this.activeRelationTabIndex === 1 && this.activeNestedRelationTabIndex > this.relationGroups.length) {
                  this.activeNestedRelationTabIndex = 0;
                } else if (oldTabIndex > 1) {
                  this.activeRelationTabIndex = 1;
                  this.activeNestedRelationTabIndex = oldTabIndex - 1;
                } else {
                  this.activeRelationTabIndex = oldTabIndex;
                }
              }

              this.loadingRelations = false;
              this.changesRef.markForCheck();
            },
            error: (err) => {
              this.toastService.error(err?.error?.message);
              this.loadingRelations = false;
              this.changesRef.markForCheck();
            }
          });
        },
        error: (err) => {
          this.toastService.error(err?.error?.message);
          this.loadingRelations = false;
          this.changesRef.markForCheck();
        }
      });
  }


  private loadGroupInstances(relationId: number, isParent: boolean, page: number, pageSize: number): void {
    const filter = isParent
      ? { $and: [{ relation_id: relationId }, { relation_parent_id: this.currentObjectID }] }
      : { $and: [{ relation_id: relationId }, { relation_child_id: this.currentObjectID }] };

    finalize(() => this.loaderService.show())

    const params = {
      filter,
      limit: pageSize,
      sort: this.relationSort,
      order: this.relationOrder,
      page: page
    };

    // Fetch the relation definition for this relationId first
    this.relationService.getRelation(relationId).pipe(
      finalize(() => this.loaderService.hide()),
      takeUntil(this.unsubscribe),
      switchMap(definition => {
        if (!definition) {
          throw new Error(`Relation definition not found for ID ${relationId}`);
        }
        // Fetch the paginated instances with the definition available
        return this.objectRelationService?.getObjectRelations(params).pipe(
          map(response => ({ definition, response }))
        );
      })
    ).subscribe({
      next: ({ definition, response }) => {
        const group = this.relationGroups?.find(g => g?.relationId === relationId && g?.isParent === isParent);
        if (group) {
          group.instances = (response?.results || []).map(inst => ({
            ...inst,
            counterpart_id: isParent ? inst?.relation_child_id : inst?.relation_parent_id,
            type: isParent ? definition?.relation_name_parent : definition?.relation_name_child,
            definition // Attach the definition to each instance
          }));
          group.total = response?.total;
          group.pageSize = pageSize;
        }
        this.changesRef.markForCheck();
      },
      error: (err) => {
        this.toastService.error(err?.error?.message);
        this.loadingRelations = false;
        this.changesRef.markForCheck();
      }
    });
  }


  /**
   * Loads available relations for creating a new relation.
   */
  private loadRelationsForNewRelation(): void {
    const typeId = this.renderResult?.type_information?.type_id;
    if (!typeId) {
      this.toastService.warning('No valid type ID found.');
      return;
    }

    this.loadingRelations = true;

    const params = {
      filter: {
        $or: [
          { parent_type_ids: { $in: [typeId] } },
          { child_type_ids: { $in: [typeId] } }
        ]
      },
      limit: 0,
      sort: '',
      order: 1,
      page: 1
    };

    this.relationService.getRelations(params)
      .pipe(takeUntil(this.unsubscribe))
      .subscribe({
        next: (response) => {
          this.availableRelations = response.results || [];

          this.extendedRelations = this.availableRelations.map(rel => {
            let canBeParent = rel?.parent_type_ids?.includes(typeId) || false;
            let canBeChild = rel?.child_type_ids?.includes(typeId) || false;

            const used = this.usedRolesMap.get(rel.public_id);
            if (used) {
              if (used?.parentUsed) {
                canBeParent = false;
              }
              if (used?.childUsed) {
                canBeChild = false;
              }
            }

            return {
              ...rel,
              canBeParent,
              canBeChild
            };
          }).filter(rel => rel?.canBeParent || rel?.canBeChild);

          this.loadingRelations = false;
          this.changesRef.detectChanges();
        },
        error: (err) => {
          this.toastService.error(err?.error?.message);
          this.loadingRelations = false;
          this.changesRef.detectChanges();
        }
      });
  }

  private loadCounterpartObjects(ids: number[]): void {
    // Remove duplicates, if necessary:
    const uniqueIDs = Array.from(new Set(ids));
    if (!uniqueIDs?.length) {
      return; // Nothing to fetch
    }

    finalize(() => this.loaderService.show())

    // Prepare filter with $in
    const params = {
      filter: { public_id: { $in: uniqueIDs } },
      limit: 0,
      sort: this.relationSort,
      order: this.relationOrder,
      page: this.relationPage
    };

    // Single request to fetch all IDs in one go
    this.objectService.getObjects(params)
      .pipe(takeUntil(this.unsubscribe), finalize(() => this.loaderService.hide()))
      .subscribe({
        next: (apiResponse) => {
          // (Re)initialize the map each time you fetch
          this.relatedObjectsMap = {};

          // Populate the map: object_id -> RenderResult (or union type)
          (apiResponse.results || []).forEach((obj) => {
            if (this.isRenderResult(obj)) {
              const id = obj?.object_information?.object_id;
              // now TS knows it's a RenderResult

              if (id) {
                this.relatedObjectsMap[id] = obj;
              }
            }
          });

          // TODO: remove: Filter relation groups to only include instances with valid counterparts (those who are inactive don't show them)
          this.relationGroups = this.relationGroups
            .map(group => {
              const filtered = group.instances.filter(inst =>
                !!this.relatedObjectsMap[inst.counterpart_id]
              );
              return {
                ...group,
                instances: filtered,
                total: filtered.length
              };
            })


          // Manually trigger CD if needed
          this.changesRef.markForCheck();
        },
        error: (err) => {
          this.toastService.error(err?.error?.message);
          this.changesRef.markForCheck();
        }
      });
  }


  /* --------------------------------------------------- HELPER & UTILITY METHODS -------------------------------------------- */


  /**
   * Returns columns for the cmdb-table based on group properties.
   * @param group The relation group
   */
  public getColumns(group: RelationGroup): any[] {
    return [
      { display: 'Object Relation ID', name: 'public_id', data: 'public_id', searchable: true, sortable: true, style: { width: '180px', 'text-align': 'center' } },
      {
        display: 'Type',
        name: 'type_label',
        data: 'type_label',
        template: this.counterpartTypeTemplate,
        style: { width: 'auto', 'text-align': 'left' }
      },
      { display: 'Relation Object', name: 'counterpart_id', data: 'counterpart_id', sortable: true, template: this.counterpartIdTemplate, style: { width: 'auto', 'text-align': 'left' } },
      // { display: group.isParent ? 'Type Parent' : 'Type Child', name: 'type', data: 'type', sortable: false },
      { display: 'Actions', name: 'actions', template: this.actionsTemplate, sortable: false, style: { width: '150px', 'text-align': 'center' } }
    ];
  }

  /** Sets the active nested relation tab index */
  // public setNestedRelationTab(tabIndex: number): void {
  //   this.activeNestedRelationTabIndex = tabIndex;
  //   this.changesRef.markForCheck();
  // }

  public setNestedRelationTab(tabIndex: number): void {
    this.activeNestedRelationTabIndex = tabIndex;
    const group = this.relationGroups[tabIndex];
    if (group) {
      // Use default page 1 and the group's pageSize (or a default value, e.g., 10)
      this.loadGroupInstances(group?.relationId, group?.isParent, 1, group?.pageSize || 10);
    }
    this.changesRef.markForCheck();
  }

  private isRenderResult(obj: CmdbObject | RenderResult): obj is RenderResult {
    return (
      obj != null &&
      typeof obj === 'object' &&
      'object_information' in obj
    );
  }

  trackByRelationId(index: number, group: RelationGroup): number {
    return group?.relationId;
  }


  toggleView(showGraph: boolean): void {
    this.isGraphView = showGraph;
  }

  /** Graph header selector change */
  public onGraphHeaderObjectChange(ids: number[]): void {
    this.pendingSelectedId = ids && ids.length ? ids[0] : null;
  }

  public openSelectedObject(): void {
    const targetId = this.pendingSelectedId ?? this.currentObjectID;
    if (!targetId || targetId === this.currentObjectID) return;
    this.router.navigate([`/framework/object/view/${targetId}`], { queryParams: { view: 'graph' } });
  }
}