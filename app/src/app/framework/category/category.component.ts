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

import { AfterViewInit, Component, ElementRef, NgZone, OnDestroy, OnInit, ViewChild } from '@angular/core';
import { BehaviorSubject, forkJoin, Observable, ReplaySubject } from 'rxjs';
import { CmdbCategory, CmdbCategoryNode, CmdbCategoryTree } from '../models/cmdb-category';
import { CategoryService } from '../services/category.service';
import { CmdbMode } from '../modes.enum';
import { ActivatedRoute, Data, Router } from '@angular/router';
import { SidebarService } from '../../layout/services/sidebar.service';
import { finalize, takeUntil } from 'rxjs/operators';
import { APIGetMultiResponse } from '../../services/models/api-response';
import { CollectionParameters } from '../../services/models/api-parameter';
import { Column, Sort, SortDirection, TableState, TableStatePayload } from '../../layout/table/table.types';
import { UserSetting } from '../../management/user-settings/models/user-setting';
import { convertResourceURL, UserSettingsService } from '../../management/user-settings/services/user-settings.service';
import { UserSettingsDBService } from '../../management/user-settings/services/user-settings-db.service';
import { LoaderService } from 'src/app/core/services/loader.service';
import { ToastService } from 'src/app/layout/toast/toast.service';

/**
 * Distance to the edge of the tree viewport that starts the auto scroll while dragging.
 */
const DRAG_SCROLL_EDGE = 44;

/**
 * Pixels the tree viewport moves per animation frame while auto scrolling.
 */
const DRAG_SCROLL_STEP = 12;

@Component({
    selector: 'cmdb-category',
    templateUrl: './category.component.html',
    styleUrls: ['./category.component.scss'],
    standalone: false
})
export class CategoryComponent implements OnInit, AfterViewInit, OnDestroy {

  /**
   * HTML ID of the table.
   * Used for user settings and table-states
   */
  public readonly id: string = 'category-list-table';

  /**
   * Global unsubscriber for http calls to the rest backend.
   */
  private unSubscribe: ReplaySubject<void> = new ReplaySubject();

  /**
   * Current category collection
   */
  public categories: Array<CmdbCategory>;
  public categoriesAPIResponse: APIGetMultiResponse<CmdbCategory>;

  /**
   * Root element of the category tree
   */
  public categoryTree: CmdbCategoryTree;

  /**
   * Tree that is actually rendered. Equals the full tree unless a filter is active.
   */
  public visibleTree: CmdbCategoryTree;

  /**
   * True while the user rearranges the tree by drag and drop.
   */
  public organizing: boolean = false;

  /**
   * True as soon as a drag and drop changed the tree but nothing was saved yet.
   */
  public hasPendingChanges: boolean = false;

  /**
   * Current filter term of the tree.
   */
  public searchTerm: string = '';

  /**
   * Category being dragged right now. Drives the drop preview and the open drop zones.
   */
  public draggedNode: CmdbCategoryNode;

  /**
   * Public IDs of all nodes whose children are currently hidden.
   */
  public readonly collapsedNodes: Set<number> = new Set<number>();

  /**
   * True when at least one category has children. Only then a collapse control makes sense.
   */
  public hasNestedCategories: boolean = false;

  /**
   * Scrollable tree viewport, used for the auto scroll while dragging.
   */
  @ViewChild('treeScroll') private treeScrollRef: ElementRef<HTMLElement>;

  /**
   * Current auto scroll direction: -1 up, 0 idle, 1 down.
   */
  private autoScrollDirection: number = 0;

  private autoScrollFrame: number = 0;

  /**
   * Table datas
   */
  public apiParameters: CollectionParameters = { limit: 10, sort: 'public_id', order: -1, page: 1};
  public tableColumns: Array<Column>;
  public totalResults: number = 0;

  /**
   * Default sort filter.
   */
  public sort: Sort = { name: 'public_id', order: SortDirection.DESCENDING } as Sort;

  public tableStateSubject: BehaviorSubject<TableState> = new BehaviorSubject<TableState>(undefined);

  public tableStates: Array<TableState> = [];

  public isLoading$ = this.loaderService.isLoading$;

  public get tableState(): TableState {
    return this.tableStateSubject.getValue() as TableState;
  }

  /**
   * Mode handed to the tree. Only the organize state decides it, not the route.
   */
  public get treeMode(): CmdbMode {
    return this.organizing ? CmdbMode.Edit : CmdbMode.View;
  }

  public get hasCategories(): boolean {
    return this.categoryTree?.length > 0;
  }

  public get isFiltered(): boolean {
    return this.searchTerm.trim().length > 0;
  }

  public get isEverythingExpanded(): boolean {
    return this.collapsedNodes.size === 0;
  }

  constructor(private categoryService: CategoryService, private route: ActivatedRoute, private sidebarService: SidebarService,
              private router: Router, private userSettingsService: UserSettingsService<UserSetting, TableStatePayload>,
              private indexDB: UserSettingsDBService<UserSetting, TableStatePayload>,
              private loaderService: LoaderService, private toastService: ToastService, private zone: NgZone
            ) {
    this.categories = [];
    this.organizing = this.route.snapshot.data.mode === CmdbMode.Edit;
    this.route.data.pipe(takeUntil(this.unSubscribe)).subscribe((data: Data) => {
      if (data.userSetting) {
        const userSettingPayloads = (data.userSetting as UserSetting<TableStatePayload>).payloads
          .find(payloads => payloads.id === this.id);
        this.tableStates = userSettingPayloads.tableStates;
        this.tableStateSubject.next(userSettingPayloads.currentState);
      } else {
        this.tableStates = [];
        this.tableStateSubject.next(undefined);

        const statePayload: TableStatePayload = new TableStatePayload(this.id, []);
        const resource: string = convertResourceURL(this.router.url.toString());
        const userSetting = this.userSettingsService.createUserSetting<TableStatePayload>(resource, [statePayload]);
        this.indexDB.addSetting(userSetting);
      }
    });
  }

  /* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

  public ngOnInit(): void {
    this.tableColumnBuilder();
    this.watchCategoryTree();
    this.loadCategories();
  }

  public ngAfterViewInit(): void {
    // dragover fires continuously, so it stays outside Angular instead of triggering change detection per event.
    this.zone.runOutsideAngular(() => {
      this.treeScrollRef?.nativeElement.addEventListener('dragover', this.handleTreeDragOver);
    });
  }

  public ngOnDestroy(): void {
    this.treeScrollRef?.nativeElement.removeEventListener('dragover', this.handleTreeDragOver);
    this.stopAutoScroll();
    this.unSubscribe?.next();
    this.unSubscribe?.complete();
  }

  /* ---------------------------------------------------- EVENTS ------------------------------------------------------ */

  public onAddCategory(): void {
    this.router.navigate(['/framework/category/add']);
  }

  public startOrganize(): void {
    this.searchTerm = '';
    this.collapsedNodes.clear();
    this.hasPendingChanges = false;
    this.organizing = true;
    this.visibleTree = this.categoryTree;
  }

  /**
   * Drops every local reorder by reloading the tree from the backend.
   */
  public cancelOrganize(): void {
    this.organizing = false;
    this.hasPendingChanges = false;
    this.endDragState();
    this.sidebarService.loadCategoryTree();
  }

  /**
   * Rest caller updates every category in tree
   */
  public onSave(): void {
    const observers = this.saveTree(this.categoryTree);

    if (observers.length === 0) {
      this.organizing = false;
      this.hasPendingChanges = false;
      return;
    }

    this.loaderService.show();
    forkJoin(observers).pipe(takeUntil(this.unSubscribe), finalize(() => this.loaderService.hide())).subscribe({
      next: () => {
        this.organizing = false;
        this.hasPendingChanges = false;
        this.endDragState();
        this.toastService.success('The category structure was saved.');
        this.sidebarService.loadCategoryTree();
        this.loadCategories();
      },
      error: () => this.toastService.error('The category structure could not be saved. Please try again.')
    });
  }

  public onTreeReorder(): void {
    this.hasPendingChanges = true;
  }

  /**
   * ngx-drag-drop stops the dragstart event at the row, so the drag state comes from the tree
   * itself instead of a listener on the viewport.
   */
  public onTreeDragStarted(node: CmdbCategoryNode): void {
    this.draggedNode = node;
  }

  /**
   * A node was removed inside the tree, so tree and list have to be reloaded.
   */
  public onTreeChange(): void {
    this.sidebarService.loadCategoryTree();
    this.loadCategories();
  }

  public onSearchInput(event: Event): void {
    this.searchTerm = (event.target as HTMLInputElement).value;
    this.collapsedNodes.clear();
    this.applyTreeFilter();
  }

  public clearSearch(): void {
    this.searchTerm = '';
    this.applyTreeFilter();
  }

  public toggleAllNodes(): void {
    if (this.collapsedNodes.size === 0) {
      this.collectParentIDs(this.categoryTree).forEach(publicID => this.collapsedNodes.add(publicID));
    } else {
      this.collapsedNodes.clear();
    }
  }

  /**
   * Ends a drag: stops the auto scroll and removes drag state ngx-drag-drop leaves behind.
   */
  public onTreeDragEnd(): void {
    this.endDragState();
  }

  /**
   * On table sort change.
   * Reload all objects.
   *
   * @param sort
   */
  public onSortChange(sort: Sort): void {
    this.sort = sort;
    this.apiParameters.sort = sort.name;
    this.apiParameters.order = sort.order;
    this.loadCategories();
  }

  /**
   * On table state reset.
   * Resets the table state
   */
  public onStateReset(): void {
    this.sort = { name: 'public_id', order: SortDirection.DESCENDING } as Sort;
    this.apiParameters.sort = this.sort.name;
    this.apiParameters.order = this.sort.order;
    this.apiParameters.limit = 10;
    this.apiParameters.page = 1;
  }

  /**
   * On Table state select.
   * Sets the current table state to the selected table state
   * @param state
   */
  public onStateSelect(state: TableState): void {
    this.tableStateSubject.next(state);
    this.apiParameters.page = this.tableState.page;
    this.apiParameters.limit = this.tableState.pageSize;
    this.sort = this.tableState.sort;
    for (const col of this.tableColumns) {
      col.hidden = !this.tableState.visibleColumns.includes(col.name);
    }
    this.loadCategories();
  }

  /**
   * On table page change.
   * Reload all objects.
   *
   * @param page
   */
  public onPageChange(page: number) {
    this.apiParameters.page = page;
    this.loadCategories();
  }

  /**
   * On table page size change.
   * Reload all objects.
   *
   * @param limit
   */
  public onPageSizeChange(limit: number): void {
    this.apiParameters.limit = limit;
    this.loadCategories();
  }

  /* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

  private tableColumnBuilder(): void {

    const publicColumn = {
      display: 'Public ID',
      name: 'public_id',
      data: 'public_id',
      cssClasses: ['text-center'],
      style: { 'white-space': 'nowrap' },
      searchable: false,
      sortable: true
    } as unknown as Column;

    const nameColumn = {
      display: 'Name',
      name: 'name',
      data: 'name',
      cssClasses: ['text-center'],
      searchable: false,
      sortable: true
    } as unknown as Column;

    const labelColumn = {
      display: 'Label',
      name: 'label',
      data: 'label',
      cssClasses: ['text-center'],
      searchable: false,
      sortable: true
    } as unknown as Column;

    const parentColumn = {
      display: 'Parent ID',
      name: 'parent',
      data: 'parent',
      cssClasses: ['text-center'],
      style: { 'white-space': 'nowrap' },
      searchable: false,
      sortable: true
    } as unknown as Column;

    this.tableColumns = [publicColumn, labelColumn, nameColumn, parentColumn];
    this.initTable();
  }

  /**
   * If a table state is available configures the
   * table according to the data specified in the table state
   * @private
   */
  private initTable() {
    if (this.tableState) {
      this.sort = this.tableState.sort;
      this.apiParameters.sort = this.sort.name;
      this.apiParameters.order = this.sort.order;
      this.apiParameters.page = this.tableState.page;
      this.apiParameters.limit = this.tableState.pageSize;
    }
  }

  /**
   * Load categories from the backend.
   */
  private loadCategories(): void {
    this.loaderService.show();
    this.categoryService.getCategories(this.apiParameters).pipe(
      takeUntil(this.unSubscribe), finalize(() => this.loaderService.hide())).subscribe((response: APIGetMultiResponse<CmdbCategory>) => {
      this.categoriesAPIResponse = response;
      this.categories = this.categoriesAPIResponse.results;
      this.totalResults = response.total;
    });
  }

  /**
   * The sidebar owns the category tree, so the page follows its state instead of loading its own copy.
   */
  private watchCategoryTree(): void {
    this.sidebarService.categoryTree.asObservable().pipe(takeUntil(this.unSubscribe))
      .subscribe((categoryTree: CmdbCategoryTree) => {
        this.categoryTree = categoryTree;
        this.hasNestedCategories = this.collectParentIDs(categoryTree).length > 0;
        this.applyTreeFilter();
      });
  }

  /**
   * Keeps a category when it matches itself or has a matching descendant.
   */
  private applyTreeFilter(): void {
    const term = this.searchTerm.trim().toLowerCase();

    if (!term || this.organizing) {
      this.visibleTree = this.categoryTree;
      return;
    }

    this.visibleTree = this.filterNodes(this.categoryTree, term);
  }

  private filterNodes(nodes: CmdbCategoryTree, term: string): CmdbCategoryTree {
    const matches: Array<CmdbCategoryNode> = [];

    for (const node of nodes ?? []) {
      const children = this.filterNodes(node.children, term);
      const isMatch = node.category.label.toLowerCase().includes(term);

      if (isMatch || children.length > 0) {
        matches.push({ category: node.category, children, types: node.types });
      }
    }

    return matches;
  }

  private collectParentIDs(nodes: CmdbCategoryTree): Array<number> {
    const parents: Array<number> = [];

    for (const node of nodes ?? []) {
      if (node.children?.length > 0) {
        parents.push(node.category.public_id, ...this.collectParentIDs(node.children));
      }
    }

    return parents;
  }

  /**
   * Recursive tree call. Will generate the observers for the calls
   * @param root node root element
   * @param parentNode node of parent
   */
  private saveTree(root: CmdbCategoryTree, parentNode?: CmdbCategoryNode): Observable<any>[] {
    let observers: Observable<any>[] = [];
    for (let i = 0; i < root.length; i++) {
      const node = root[i];
      node.category.meta.order = i + 1;
      if (parentNode) {
        node.category.parent = parentNode.category.public_id;
      }
      if (!parentNode && node.category.parent !== null) {
        node.category.parent = null;
      }
      observers.push(this.categoryService.updateCategory(node.category));
      if (node.children.length > 0) {
        observers = observers.concat(this.saveTree(node.children, node));
      }
    }
    return observers;
  }

  private endDragState(): void {
    this.draggedNode = null;
    this.stopAutoScroll();
    this.clearStaleDragState();
  }

  /**
   * ngx-drag-drop has no auto scroll, so dragging towards an edge of the tree viewport moves it here.
   */
  private readonly handleTreeDragOver = (event: DragEvent): void => {
    const viewport = this.treeScrollRef?.nativeElement;

    if (!viewport || viewport.scrollHeight <= viewport.clientHeight) {
      this.autoScrollDirection = 0;
      return;
    }

    const bounds = viewport.getBoundingClientRect();

    if (event.clientY < bounds.top + DRAG_SCROLL_EDGE) {
      this.autoScrollDirection = -1;
    } else if (event.clientY > bounds.bottom - DRAG_SCROLL_EDGE) {
      this.autoScrollDirection = 1;
    } else {
      this.autoScrollDirection = 0;
    }

    this.ensureAutoScroll();
  };

  private ensureAutoScroll(): void {
    if (this.autoScrollFrame || this.autoScrollDirection === 0) {
      return;
    }

    this.zone.runOutsideAngular(() => {
      const step = () => {
        const viewport = this.treeScrollRef?.nativeElement;

        if (!viewport || this.autoScrollDirection === 0) {
          this.autoScrollFrame = 0;
          return;
        }

        viewport.scrollTop += this.autoScrollDirection * DRAG_SCROLL_STEP;
        this.autoScrollFrame = requestAnimationFrame(step);
      };

      this.autoScrollFrame = requestAnimationFrame(step);
    });
  }

  private stopAutoScroll(): void {
    this.autoScrollDirection = 0;

    if (this.autoScrollFrame) {
      cancelAnimationFrame(this.autoScrollFrame);
      this.autoScrollFrame = 0;
    }
  }

  /**
   * ngx-drag-drop skips its own cleanup when a drop lands on a nested dropzone, which leaves the
   * highlight and the placeholder of the passed zones behind. Both are recreated on the next drag.
   */
  private clearStaleDragState(): void {
    const viewport = this.treeScrollRef?.nativeElement;

    if (!viewport) {
      return;
    }

    viewport.querySelectorAll('.dndDragover').forEach(element => element.classList.remove('dndDragover'));
    viewport.querySelectorAll('.dg-tree__placeholder').forEach(element => element.remove());
  }
}
