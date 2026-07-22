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
import { Component, inject, EventEmitter, Input, OnInit, Output, OnChanges, OnDestroy, SimpleChanges } from '@angular/core';
import { CollectionParameters } from 'src/app/services/models/api-parameter';
import { APIGetMultiResponse } from 'src/app/services/models/api-response';
import { LoaderService } from 'src/app/core/services/loader.service';
import {
  BehaviorSubject,
  Observable,
  Subject,
  catchError,
  debounceTime,
  distinctUntilChanged,
  finalize,
  of,
  switchMap,
  takeUntil,
  tap
} from 'rxjs';
import { RenderResult } from 'src/app/framework/models/cmdb-render';
import { ObjectService } from 'src/app/framework/services/object.service';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { InfiniteScrollService } from 'src/app/layout/services/infinite-scroll.service';
import { ObjectSearchFilterService } from 'src/app/core/services/object-search-filter.service';

@Component({
  selector: 'app-object-selector',
  templateUrl: './object-selector.component.html',
  styleUrls: ['./object-selector.component.scss'],
  standalone: false
})
export class ObjectSelectorComponent implements OnInit, OnChanges, OnDestroy {
  private readonly objectService = inject(ObjectService);
  private readonly loaderService = inject(LoaderService);
  private readonly toast = inject(ToastService);
  private readonly infiniteScrollService = inject(InfiniteScrollService);
  private readonly objectSearchFilterService = inject(ObjectSearchFilterService);

  @Input() typeIds: number[] = [];
  @Input() allObjects = false;
  @Input() multiple = false;
  @Input() selectedIds: any[] = [];
  @Input() isViewMode = false;
  @Input() useInlineLoader = false;
  @Input() includeFields = false;
  @Input() closeOnSelect = false;
  @Input() excludeIds: number[] = [];
  @Output() selectionChange = new EventEmitter<number[]>();
  @Output() fullSelectionChange = new EventEmitter<RenderResult | RenderResult[] | null>();
  @Output() loadingChange = new EventEmitter<boolean>();

  public objectList: RenderResult[] = [];
  public selectedObjects: RenderResult[] | RenderResult | null = null;
  private inlineLoading$ = new BehaviorSubject<boolean>(false);
  public isLoading$ = this.loaderService.isLoading$;

  // Pagination properties
  private currentPage: number = 1;
  private pageSize: number = 10;
  private hasMoreData: boolean = true;
  private isSearching: boolean = false;
  private searchTerm: string = '';
  public searchSubject = new Subject<string>();
  private isLoading: boolean = false;
  private loadingRequests: number = 0;

  // Objects that are pre-selected (edit/view mode). Fetched by id so they render
  // as selected regardless of which pagination page they naturally belong to.
  private preselectedObjects: RenderResult[] = [];

  // Request pipelines. Each uses switchMap so a newer request supersedes and
  // cancels an in-flight one, preventing out-of-order responses.
  private readonly optionsRequest$ = new Subject<{ resetPagination: boolean }>();
  private readonly selectedRequest$ = new Subject<void>();
  private readonly destroy$ = new Subject<void>();

  // Last resolved input values, compared by value so that consumers passing a
  // fresh array reference on every change-detection cycle do not trigger a
  // refetch when the actual ids/scope have not changed.
  private lastTypeScopeKey: string | null = null;
  private lastSelectedKey: string | null = null;

  // Unique identifier for infinite scroll
  private readonly scrollUniqueId = 'object-selector-scroll';

  /* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

  ngOnInit(): void {
    this.isLoading$ = this.useInlineLoader ? this.inlineLoading$.asObservable()
      : this.loaderService.isLoading$;

    // Debounced search input.
    this.searchSubject.pipe(
      debounceTime(800),
      distinctUntilChanged(),
      takeUntil(this.destroy$)
    ).subscribe(searchTerm => this.handleSearch(searchTerm));

    // Options pipeline (paginated / search results).
    this.optionsRequest$.pipe(
      switchMap(({ resetPagination }) => this.runOptionsFetch(resetPagination)),
      takeUntil(this.destroy$)
    ).subscribe();

    // Pre-selected objects pipeline (fetched by id, independent of the options).
    this.selectedRequest$.pipe(
      switchMap(() => this.runSelectedFetch()),
      takeUntil(this.destroy$)
    ).subscribe();

    // Establish the baseline before the initial fetches so subsequent
    // ngOnChanges only refetch on real value changes.
    this.lastTypeScopeKey = this.typeScopeKey();
    this.lastSelectedKey = this.selectedIdsKey();

    this.requestOptions(true);
    this.requestSelectedObjects();
  }

  ngOnChanges(changes: SimpleChanges): void {
<<<<<<< HEAD
    // Refetch when object scope changes.
    if ((changes.typeIds && !changes.typeIds.firstChange) ||
        (changes.allObjects && !changes.allObjects.firstChange)) {
      this.fetchObjects(true);
    }
  }

  private fetchObjects(resetPagination: boolean = true): void {
    if (!this.allObjects && (!this.typeIds || this.typeIds.length === 0)) {
      this.initSelectedObjects();
=======
    // Refetch when object scope changes, but only when the resolved value
    // actually differs (guards against new-array-every-tick bindings).
    if ((changes.typeIds && !changes.typeIds.firstChange) ||
      (changes.allObjects && !changes.allObjects.firstChange)) {
      const key = this.typeScopeKey();
      if (key !== this.lastTypeScopeKey) {
        this.lastTypeScopeKey = key;
        this.requestOptions(true);
      }
    }

    // Selected ids usually arrive asynchronously in edit mode. Reload the
    // selected objects by id so they display even when they belong to a page
    // that has not been paginated into the list yet.
    if (changes.selectedIds && !changes.selectedIds.firstChange) {
      const key = this.selectedIdsKey();
      if (key !== this.lastSelectedKey) {
        this.lastSelectedKey = key;
        this.requestSelectedObjects();
      }
    }
  }

  ngOnDestroy(): void {
    this.destroy$.next();
    this.destroy$.complete();
  }

  /* ---------------------------------------------------- EVENTS ------------------------------------------------------ */

  /**
   * Handle scroll to end event for infinite scroll
   */
  public onScrollToEnd(): void {
    if (!this.isSearching && this.hasMoreData && !this.isLoading) {
      this.requestOptions(false);
    }
  }

  /**
   * Handle search input changes
   */
  public onSearch(searchTerm: string): void {
    this.searchSubject.next(searchTerm);
  }

  public onSelectionChange(selectedValue: RenderResult | RenderResult[] | null): void {
    // Case 1: selectedValue is null or undefined
    if (!selectedValue) {
      this.selectedObjects = this.multiple ? [] : null;
      this.selectionChange.emit([]);
      this.fullSelectionChange.emit(null);
>>>>>>> origin/version-3.2
      return;
    }

    // Case 2: Multiple selection (expecting an array)
    if (this.multiple) {
      if (Array.isArray(selectedValue)) {
        this.selectedObjects = selectedValue; // Type: RenderResult[]
        const idArray = selectedValue
          .map(obj => obj?.object_information?.object_id)
          .filter((id): id is number => id != null);
        this.selectionChange.emit(idArray);
        this.fullSelectionChange.emit(selectedValue);
      }
    }
    // Case 3: Single selection (expecting a single object)
    else {
      if (!Array.isArray(selectedValue)) {
        this.selectedObjects = selectedValue; // Type: RenderResult
        const id = selectedValue?.object_information?.object_id;
        this.selectionChange.emit(id != null ? [id] : []);
        this.fullSelectionChange.emit(selectedValue);
      }
    }
  }

  /* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

  /**
   * Clear search and reset to pagination mode
   */
  public clearSearch(): void {
    this.searchTerm = '';
    this.isSearching = false;
    this.requestOptions(true);
  }

  /* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

  private requestOptions(resetPagination: boolean): void {
    this.optionsRequest$.next({ resetPagination });
  }

  private requestSelectedObjects(): void {
    this.selectedRequest$.next();
  }

  /**
   * Process search with debouncing
   */
  private handleSearch(searchTerm: string): void {
    const term = (searchTerm ?? '').trim();
    this.isSearching = term.length > 0;
    this.searchTerm = this.isSearching ? searchTerm : '';
    this.requestOptions(true);
  }

  /**
   * Builds the options request. Returns an observable so the pipeline's
   * switchMap can cancel it when a newer request arrives.
   */
  private runOptionsFetch(resetPagination: boolean): Observable<APIGetMultiResponse<RenderResult> | null> {
    // In view mode the control is read-only. The selected objects are loaded by
    // their ids through the dedicated pipeline, so there are no browsable
    // options to paginate and no need for a second overlapping request.
    if (this.isViewMode) {
      this.initSelectedObjects();
      return of(null);
    }

    if (!this.allObjects && (!this.typeIds || this.typeIds.length === 0)) {
      // No scope to query: drop any previously loaded options so they don't
      // linger after the type selection is cleared.
      this.objectList = [];
      this.hasMoreData = false;
      this.currentPage = 1;
      this.initSelectedObjects();
      return of(null);
    }

    if (resetPagination) {
      this.currentPage = 1;
      this.hasMoreData = true;
      this.objectList = [];
    }

<<<<<<< HEAD
    // Build filters based on mode
=======
>>>>>>> origin/version-3.2
    const effectiveTypeIds = this.allObjects ? undefined : this.typeIds;
    const filters = this.objectSearchFilterService.buildSearchPipeline(
      this.isSearching ? this.searchTerm : '',
      effectiveTypeIds
<<<<<<< HEAD
=======
    );

    const params: CollectionParameters = {
      filter: filters,
      projection: this.buildProjection(),
      limit: this.isSearching ? 0 : this.pageSize, // In search mode, get all results
      sort: 'type_id',
      order: 1,
      page: this.isSearching ? 1 : this.currentPage
    };

    this.setLoading(true);
    return this.objectService.getObjects(params).pipe(
      tap((response: APIGetMultiResponse<RenderResult>) => this.applyOptionsResponse(response, resetPagination)),
      catchError((err) => {
        this.toast.error(err?.error?.message);
        this.objectList = [];
        this.initSelectedObjects();
        return of(null);
      }),
      finalize(() => this.setLoading(false))
>>>>>>> origin/version-3.2
    );
  }

  private applyOptionsResponse(response: APIGetMultiResponse<RenderResult>, resetPagination: boolean): void {
    const rawResultCount = response.results?.length || 0;
    const incomingResults = this.applyExclusions(this.getUniqueObjectsById(response.results || []));

    if (resetPagination) {
      // Keep the pre-selected objects available as options so they stay
      // visible after a reset (search mode shows only matching results).
      this.objectList = this.isSearching
        ? incomingResults
        : this.getUniqueObjectsById([...this.preselectedObjects, ...incomingResults]);
    } else {
      this.objectList = this.getUniqueObjectsById([...this.objectList, ...incomingResults]);
    }

    // Update hasMoreData for pagination mode. Base it on the raw response
    // count so that filtering out excluded objects never stops pagination early.
    if (!this.isSearching) {
      this.hasMoreData = rawResultCount === this.pageSize;
      this.currentPage++;
    }

<<<<<<< HEAD
    // Conditionally include fields if requested
    if (this.includeFields) {
      baseProjection['fields'] = 1;
      baseProjection['sections'] = 1;
=======
    this.initSelectedObjects();

    if (!this.isSearching) {
      this.infiniteScrollService.setCollectionParameters(
        this.currentPage,
        this.pageSize,
        'public_id',
        1,
        this.scrollUniqueId
      );
>>>>>>> origin/version-3.2
    }
  }

<<<<<<< HEAD
    this.params = {
      filter: filters,
      projection: baseProjection,
      limit: this.isSearching ? 0 : this.pageSize, // In search mode, get all results
      sort: 'type_id',
=======
  /**
   * Load the currently selected objects directly by their ids.
   *
   * Pagination only holds the pages the user has scrolled through, so a
   * pre-selected object that lives on a later page would never resolve to a
   * full object and therefore never render as selected in edit/view mode.
   * Fetching the ids explicitly guarantees their data is available for the
   * ng-select value regardless of the current page.
   */
  private runSelectedFetch(): Observable<APIGetMultiResponse<RenderResult> | null> {
    const numericIds = this.getNumericSelectedIds();

    if (numericIds.length === 0) {
      this.preselectedObjects = [];
      this.initSelectedObjects();
      return of(null);
    }

    const params: CollectionParameters = {
      filter: [{ $match: { public_id: { $in: numericIds } } }],
      projection: this.buildProjection(),
      limit: 0,
      sort: 'public_id',
>>>>>>> origin/version-3.2
      order: 1,
      page: 1
    };

    this.setLoading(true);
<<<<<<< HEAD
    this.objectService.getObjects(this.params).pipe(
      // delay(1000), // Remove delay for immediate response
      finalize(() => this.setLoading(false))
    ).subscribe({
      next: (response: APIGetMultiResponse<RenderResult>) => {
        const incomingResults = this.getUniqueObjectsById(response.results || []);

        if (resetPagination) {
          this.objectList = incomingResults;
        } else {
          this.objectList = this.getUniqueObjectsById([...this.objectList, ...incomingResults]);
        }
        
        // Update hasMoreData for pagination mode
        if (!this.isSearching) {
          this.hasMoreData = incomingResults.length === this.pageSize;
          // Advance page after each successful non-search fetch:
          // reset fetch (page 1) -> next page becomes 2
          // incremental fetch (page N) -> next page becomes N + 1
          this.currentPage++;
=======
    return this.objectService.getObjects(params).pipe(
      tap((response: APIGetMultiResponse<RenderResult>) => {
        this.preselectedObjects = this.getUniqueObjectsById(response.results || []);

        // Surface the selected objects as options too (outside of search mode)
        // so the dropdown reflects them as already selected.
        if (!this.isSearching) {
          this.objectList = this.getUniqueObjectsById([...this.preselectedObjects, ...this.objectList]);
>>>>>>> origin/version-3.2
        }

        this.initSelectedObjects();
      }),
      catchError((err) => {
        this.toast.error(err?.error?.message);
        this.initSelectedObjects();
        return of(null);
      }),
      finalize(() => this.setLoading(false))
    );
  }

<<<<<<< HEAD
  private getUniqueObjectsById(objects: RenderResult[]): RenderResult[] {
    const uniqueByObjectId = new Map<number, RenderResult>();
    for (const obj of objects) {
      const objectId = obj?.object_information?.object_id;
      if (objectId !== undefined && objectId !== null && !uniqueByObjectId.has(objectId)) {
        uniqueByObjectId.set(objectId, obj);
      }
    }
    return Array.from(uniqueByObjectId.values());
  }

  private initSelectedObjects(): void {
    const numericIds: number[] = (this.selectedIds || []).map(item => {
      if (typeof item === 'number') {
        return item;
      } else if (item && item.object_information?.object_id) {
        return item.object_information.object_id;
      }
      return null;
    }).filter(x => x !== null) as number[];
=======
  private buildProjection(): Record<string, number> {
    const projection: Record<string, number> = {
      'object_information.object_id': 1,
      'object_information.public_id': 1,
      'summary_line': 1,
      'type_information': 1
    };
>>>>>>> origin/version-3.2

    if (this.includeFields) {
      projection['fields'] = 1;
      projection['sections'] = 1;
    }

    return projection;
  }

  private applyExclusions(objects: RenderResult[]): RenderResult[] {
    if (!this.excludeIds?.length) {
      return objects;
    }
    return objects.filter(obj => !this.excludeIds.includes(obj?.object_information?.object_id));
  }

  private getUniqueObjectsById(objects: RenderResult[]): RenderResult[] {
    const uniqueByObjectId = new Map<number, RenderResult>();
    for (const obj of objects) {
      const objectId = obj?.object_information?.object_id;
      if (objectId !== undefined && objectId !== null && !uniqueByObjectId.has(objectId)) {
        uniqueByObjectId.set(objectId, obj);
      }
    }
    return Array.from(uniqueByObjectId.values());
  }

  private getNumericSelectedIds(): number[] {
    return (this.selectedIds || []).map(item => {
      if (typeof item === 'number') {
        return item;
      }
      if (item && item.object_information?.object_id != null) {
        return item.object_information.object_id;
      }
      return null;
    }).filter((id): id is number => id !== null);
  }

  private typeScopeKey(): string {
    const ids = (this.typeIds || []).slice().sort((a, b) => a - b).join(',');
    return `${this.allObjects}|${ids}`;
  }

  private selectedIdsKey(): string {
    return this.getNumericSelectedIds().slice().sort((a, b) => a - b).join(',');
  }

  private initSelectedObjects(): void {
    const numericIds = this.getNumericSelectedIds();
    // Resolve the value from both the pre-selected objects and the paginated
    // list, so the selection survives regardless of which page is loaded.
    const pool = this.getUniqueObjectsById([...this.preselectedObjects, ...this.objectList]);

    if (this.multiple) {
      this.selectedObjects = pool.filter(obj =>
        numericIds.includes(obj.object_information.object_id)
      );
    } else {
      const id = numericIds[0]; // Take the first ID for single selection
      this.selectedObjects = id != null
        ? pool.find(obj => obj.object_information.object_id === id) || null
        : null;
    }
  }

  private setLoading(isLoading: boolean): void {
    // Ref-count in-flight requests so the concurrent page and by-id fetches do
    // not toggle the loader off while the other is still running.
    this.loadingRequests = Math.max(0, this.loadingRequests + (isLoading ? 1 : -1));
    const active = this.loadingRequests > 0;
    this.isLoading = active;

    if (this.useInlineLoader) {
      this.inlineLoading$.next(active);
      this.loadingChange.emit(active);
    } else {
      isLoading ? this.loaderService.show() : this.loaderService.hide();
    }
  }

  public compareObjects = (a: RenderResult, b: RenderResult): boolean =>
    a?.object_information?.object_id === b?.object_information?.object_id;

  public groupByFn = (item: RenderResult) => item?.type_information?.type_label;
  public groupValueFn = (_: string, children: RenderResult[]) => ({
    name: children?.[0]?.type_information?.type_label,
    total: children?.length ?? 0
  });
}
