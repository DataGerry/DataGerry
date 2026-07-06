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
import { Component, inject, EventEmitter, Input, OnInit, Output, OnChanges, SimpleChanges } from '@angular/core';
import { CollectionParameters } from 'src/app/services/models/api-parameter';
import { APIGetMultiResponse } from 'src/app/services/models/api-response';
import { LoaderService } from 'src/app/core/services/loader.service';
import { BehaviorSubject, finalize, Subject, debounceTime, distinctUntilChanged } from 'rxjs';
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
export class ObjectSelectorComponent implements OnInit, OnChanges {
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
  @Output() selectionChange = new EventEmitter<number[]>();
  @Output() fullSelectionChange = new EventEmitter<RenderResult | RenderResult[] | null>();
  @Output() loadingChange = new EventEmitter<boolean>();

  public objectList: RenderResult[] = [];
  public selectedObjects: RenderResult[] | RenderResult | null = null; // Updated type
  private inlineLoading$ = new BehaviorSubject<boolean>(false);
  public isLoading$ = this.loaderService.isLoading$;
  private params: CollectionParameters = null;

  // Pagination properties
  private currentPage: number = 1;
  private pageSize: number = 10;
  private hasMoreData: boolean = true;
  private isSearching: boolean = false;
  private searchTerm: string = '';
  public searchSubject = new Subject<string>();
  private isLoading: boolean = false;

  // Unique identifier for infinite scroll
  private readonly scrollUniqueId = 'object-selector-scroll';

  ngOnInit(): void {
    this.isLoading$ = this.useInlineLoader ? this.inlineLoading$.asObservable()
    : this.loaderService.isLoading$;
    
    // Set up search debouncing
    this.searchSubject.pipe(
      debounceTime(800),
      distinctUntilChanged()
    ).subscribe(searchTerm => {
      this.handleSearch(searchTerm);
    });

    this.fetchObjects();
  }

  ngOnChanges(changes: SimpleChanges): void {
    // Refetch when object scope changes.
    if ((changes.typeIds && !changes.typeIds.firstChange) ||
        (changes.allObjects && !changes.allObjects.firstChange)) {
      this.fetchObjects(true);
    }
  }

  private fetchObjects(resetPagination: boolean = true): void {
    if (!this.allObjects && (!this.typeIds || this.typeIds.length === 0)) {
      this.initSelectedObjects();
      return;
    }

    if (resetPagination) {
      this.currentPage = 1;
      this.hasMoreData = true;
      this.objectList = [];
    }

    // Build filters based on mode
    const effectiveTypeIds = this.allObjects ? undefined : this.typeIds;
    const filters = this.objectSearchFilterService.buildSearchPipeline(
      this.isSearching ? this.searchTerm : '',
      effectiveTypeIds
    );

    if (this.isViewMode && this.selectedIds?.length) {
      filters.push({ $match: { public_id: { $in: this.selectedIds } } });
    }

    const baseProjection: any = {
      'object_information.object_id': 1,
      'object_information.public_id': 1,
      'summary_line': 1,
      'type_information': 1
    };

    // Conditionally include fields if requested
    if (this.includeFields) {
      baseProjection['fields'] = 1;
      baseProjection['sections'] = 1;
    }

    this.params = {
      filter: filters,
      projection: baseProjection,
      limit: this.isSearching ? 0 : this.pageSize, // In search mode, get all results
      sort: 'type_id',
      order: 1,
      page: this.isSearching ? 1 : this.currentPage
    };

    this.setLoading(true);
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
        }
        
        this.initSelectedObjects();
        
        // Set infinite scroll parameters
        if (!this.isSearching) {
          this.infiniteScrollService.setCollectionParameters(
            this.currentPage, 
            this.pageSize, 
            'public_id', 
            1, 
            this.scrollUniqueId
          );
        }
      },
      error: (err) => {
        this.toast.error(err?.error?.message);
        this.objectList = [];
        this.initSelectedObjects();
      }
    });
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

  private initSelectedObjects(): void {
    const numericIds: number[] = (this.selectedIds || []).map(item => {
      if (typeof item === 'number') {
        return item;
      } else if (item && item.object_information?.object_id) {
        return item.object_information.object_id;
      }
      return null;
    }).filter(x => x !== null) as number[];

    if (this.multiple) {
      this.selectedObjects = this.objectList.filter(obj =>
        numericIds.includes(obj.object_information.object_id)
      );
    } else {
      const id = numericIds[0]; // Take the first ID for single selection
      this.selectedObjects = id ? this.objectList.find(obj => obj.object_information.object_id === id) || null : null;
    }
  }

  /**
   * Handle scroll to end event for infinite scroll
   */
  public onScrollToEnd(): void {
    if (!this.isSearching && this.hasMoreData && !this.isLoading) {
      this.fetchObjects(false); // Don't reset pagination
    }
  }

  /**
   * Handle search input changes
   */
  public onSearch(searchTerm: string): void {
    this.searchSubject.next(searchTerm);
  }

  /**
   * Process search with debouncing
   */
  private handleSearch(searchTerm: string): void {
    this.searchTerm = searchTerm;
    
    if (searchTerm && searchTerm.length > 0) {
      // Enter search mode
      this.isSearching = true;
      this.fetchObjects(true);
    } else {
      // Exit search mode and return to pagination
      this.isSearching = false;
      this.searchTerm = '';
      this.fetchObjects(true);
    }
  }

  /**
   * Clear search and reset to pagination mode
   */
  public clearSearch(): void {
    this.searchTerm = '';
    this.isSearching = false;
    this.fetchObjects(true);
  }

  public onSelectionChange(selectedValue: RenderResult | RenderResult[] | null): void {
    // Case 1: selectedValue is null or undefined
    if (!selectedValue) {
      this.selectedObjects = this.multiple ? [] : null;
      this.selectionChange.emit([]);
      this.fullSelectionChange.emit(null);
      return;
    }
  
    // Case 2: Multiple selection (expecting an array)
    if (this.multiple) {
      if (Array.isArray(selectedValue)) {
        this.selectedObjects = selectedValue; // Type: RenderResult[]
        const idArray = selectedValue.map(obj => obj.object_information.object_id);
        this.selectionChange.emit(idArray);
        this.fullSelectionChange.emit(selectedValue);
      } else {
      }
    }
    // Case 3: Single selection (expecting a single object)
    else {
      if (!Array.isArray(selectedValue)) {
        this.selectedObjects = selectedValue; // Type: RenderResult
        this.selectionChange.emit([selectedValue.object_information.object_id]);
        this.fullSelectionChange.emit(selectedValue);
      } else {
      }
    }
  }

  private setLoading(isLoading: boolean): void {
    this.isLoading = isLoading;
    if (this.useInlineLoader) {
      this.inlineLoading$.next(isLoading);
      this.loadingChange.emit(isLoading);
    } else {
      isLoading ? this.loaderService.show() : this.loaderService.hide();
    }
  }

  public groupByFn = (item: RenderResult) => item.type_information.type_label;
  public groupValueFn = (_: string, children: RenderResult[]) => ({
    name: children[0].type_information.type_label,
    total: children.length
  });
}
