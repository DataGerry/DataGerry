import { Component, inject, EventEmitter, Input, OnInit, Output, TemplateRef, ViewChild } from '@angular/core';
import { debounceTime, distinctUntilChanged, finalize, switchMap } from 'rxjs/operators';
import { NgbModal } from '@ng-bootstrap/ng-bootstrap';

import { ToastService } from 'src/app/layout/toast/toast.service';
import { LoaderService } from 'src/app/core/services/loader.service';
import { ImpactCategory } from 'src/app/toolbox/isms/models/impact-category.model';
import { ImpactCategoryService } from 'src/app/toolbox/isms/services/impact-category.service';
import { Impact } from 'src/app/toolbox/isms/models/impact.model';
import { ImpactService } from 'src/app/toolbox/isms/services/impact.service';

import { ImpactCategoryModalComponent } from './modal/impact-category-modal.component';
import { IsmsConfig } from 'src/app/toolbox/isms/models/isms-config.model';

import { CoreDeleteConfirmationModalComponent } from 'src/app/core/components/dialog/delete-dialog/core-delete-confirmation-modal.component';
import { Sort, SortDirection } from 'src/app/layout/table/table.types';
import { Subject } from 'rxjs';

@Component({
    selector: 'app-isms-impact-categories',
    templateUrl: './impact-categories.component.html',
    styleUrls: ['./impact-categories.component.scss'],
    standalone: false
})
export class ImpactCategoriesComponent implements OnInit {
  private readonly impactCategoryService = inject(ImpactCategoryService);
  private readonly impactService = inject(ImpactService);
  private readonly toast = inject(ToastService);
  private readonly modalService = inject(NgbModal);
  private readonly loaderService = inject(LoaderService);

  @ViewChild('actionsTemplate', { static: true }) actionsTemplate: TemplateRef<any>;
  @ViewChild('impactDescriptionsTemplate', { static: true }) impactDescriptionsTemplate: TemplateRef<any>;
  @Input() config: IsmsConfig;
  @Output() impactCategoriesCountChange = new EventEmitter<number>();

  public impactCategories: ImpactCategory[] = [];
  public totalImpactCategories = 0;
  public page = 1;
  public limit = 10;
  public loading = false;
  public columns: Array<any>;
  private orderChangeSubject = new Subject<ImpactCategory[]>();
  private impactMap = new Map<number, string>();
  public filter: string;
  public isLoading$ = this.loaderService.isLoading$; 

  ngOnInit(): void {
    this.columns = [
      // {
      //   display: 'Public ID',
      //   name: 'publicId',
      //   data: 'public_id',
      //   searchable: false,
      //   sortable: false,
      //   style: { width: '90px', 'text-align': 'center' }
      // },
      {
        display: 'Name',
        name: 'name',
        data: 'name',
        sortable: false,
        style: { width: 'auto' },
        cssClasses: ['text-center'],

      },
      {
        display: 'Impact level descriptions',
        name: 'impact_descriptions',
        template: this.impactDescriptionsTemplate,
        sortable: false,
        style: { width: 'auto'},
        cssClasses: ['text-center'],

      },
      {
        display: 'Actions',
        name: 'actions',
        template: this.actionsTemplate,
        sortable: false,
        style: { width: '140px', 'text-align': 'center' }
      }
    ];

    // First, fetch all impacts so we can build a map from impact_id => name
    this.fetchAllImpactsAndThenLoadCategories();
    this.setupDebouncedOrderChange();
  }


  /**
   * Fetch all impacts and build impact map.
   */
  private fetchAllImpactsAndThenLoadCategories(): void {
    const sort: Sort = { name: 'calculation_basis', order: SortDirection.DESCENDING } as Sort;
    this.impactService
      .getImpacts({ filter: '', limit: 0, page: 1, sort: sort.name, order: sort.order })
      .subscribe({
        next: (data) => {
          // Build impactMap and also record the order in an array
          data.results.forEach((imp: Impact, index: number) => {
            if (imp.public_id !== undefined) {
              this.impactMap.set(imp.public_id, imp.name);
            }
          });
          this.loadImpactCategories();
        },
        error: (err) => {
          this.toast.error(err?.error?.message);
        }
      });
  }

  /**
   * Load impact categories list.
   */
  private loadImpactCategories(): void {
    this.loading = true;
    this.loaderService.show();

    this.impactCategoryService
      .getImpactCategories({
        filter: this.filterBuilder(),
        limit: this.limit,
        page: this.page,
        sort: 'sort',
        order: 1
      })
      .pipe(finalize(() => {
        this.loaderService.hide();
        this.loading = false;
      }))
      .subscribe({
        next: (data) => {
          this.impactCategories = data.results;
          this.totalImpactCategories = data.total;
          this.impactCategoriesCountChange.emit(this.impactCategories.length);
          // Reorder each category's impact_descriptions to follow the order from getImpacts
          this.reorderImpactDescriptions();
        },
        error: (err) => {
          this.impactCategories = [];
          this.totalImpactCategories = 0;
          this.impactCategoriesCountChange.emit(0);
          this.toast.error(err?.error?.message);
        }
      });
  }

  /**
   * Reorders impact_descriptions in each ImpactCategory to match the order of impacts from getImpacts.
   */
  private reorderImpactDescriptions(): void {
    // Build an index map from impact_id to its order (using the order from impactMap insertion)
    // Since Map preserves insertion order, we can extract an array of keys in order.
    const orderedImpactIds = Array.from(this.impactMap.keys());
    const indexMap = new Map<number, number>();
    orderedImpactIds.forEach((id, index) => {
      indexMap.set(id, index);
    });

    // For each ImpactCategory, sort its impact_descriptions array based on indexMap
    this.impactCategories.forEach((category) => {
      if (category.impact_descriptions && category.impact_descriptions.length > 0) {
        category.impact_descriptions.sort((a, b) => {
          // Get index from indexMap; if not found, use a high number to push it to the end.
          const idxA = indexMap.get(a.impact_id) ?? Number.MAX_SAFE_INTEGER;
          const idxB = indexMap.get(b.impact_id) ?? Number.MAX_SAFE_INTEGER;
          return idxA - idxB;
        });
      }
    });
  }



  /**
   * Opens the Add modal
   */
  public addImpactCategory(): void {
    const modalRef = this.modalService.open(ImpactCategoryModalComponent, { size: 'lg' });
    modalRef.componentInstance.sort = this.totalImpactCategories;
    modalRef.result.then(
      (result) => {
        if (result === 'saved') {
          this.loadImpactCategories();
        }
      },
      () => { }
    );
  }


  /**
   * Opens the Edit modal
   */
  public editImpactCategory(item: ImpactCategory): void {
    const modalRef = this.modalService.open(ImpactCategoryModalComponent, { size: 'lg' });
    modalRef.componentInstance.impactCategory = { ...item };
    modalRef.result.then(
      (result) => {
        if (result === 'saved') {
          this.loadImpactCategories();
        }
      },
      () => { }
    );
  }


  /**
   * Opens the modal in view mode
   */
  public viewImpactCategory(item: ImpactCategory): void {
    const modalRef = this.modalService.open(ImpactCategoryModalComponent, { size: 'lg' });
    // Pass the category
    modalRef.componentInstance.impactCategory = { ...item };
    // Indicate read-only mode
    modalRef.componentInstance.isViewMode = true;

    modalRef.result.then(
      () => { },
      () => { }
    );
  }


  /**
   * Opens the delete confirmation
   */
  public deleteImpactCategory(item: ImpactCategory): void {
    const modalRef = this.modalService.open(CoreDeleteConfirmationModalComponent, { size: 'lg' });
    modalRef.componentInstance.title = 'Delete Impact Category';
    modalRef.componentInstance.item = item;
    modalRef.componentInstance.itemType = 'Impact Category';
    modalRef.componentInstance.itemName = item.name;

    modalRef.result.then(
      (result) => {
        if (result === 'confirmed') {
          this.loading = true;
          this.loaderService.show();
          this.impactCategoryService
            .deleteImpactCategory(item.public_id!)
            .pipe(finalize(() => this.loaderService.hide()))
            .subscribe({
              next: () => {
                this.toast.success('Impact Category deleted successfully.');
                this.loadImpactCategories();
              },
              error: (err) => {
                this.toast.error(err?.error?.message);
              }
            });
        }
      },
      () => { }
    );
  }

  /**
   * Builds filter query.
   */
  private filterBuilder(): any[] {
    const query: any[] = [];
    if (this.filter) {
      // Build an $or condition for "name" and for public_id as string.
      const or: any[] = [];
      or.push({ name: { $regex: this.filter, $options: 'i' } });
      // Use $toString to convert public_id to string if necessary.
      or.push({ public_id: { $regex: this.filter, $options: 'i' } });
      query.push({ $match: { $or: or } });
    }
    return query;
  }

  // Method to handle search changes from the table
  public onSearchChange(search: string): void {
    this.filter = search;
    this.page = 1; // Reset to first page on search change
    this.loadImpactCategories();
  }

  /**
   * Table pagination
   */
  public onPageChange(newPage: number): void {
    this.page = newPage;
    this.loadImpactCategories();
  }


  /**
   * Page size changes
   */
  public onPageSizeChange(newLimit: number): void {
    this.limit = newLimit;
    this.page = 1;
    this.loadImpactCategories();
  }


  /**
   * A helper to map an impact_id to an Impact name
   */
  public getImpactName(impact_id: number): string {
    return this.impactMap.get(impact_id);
  }

  /**
    * handle row reordering
    */
  public onOrderChange(newItems: ImpactCategory[]): void {
    this.impactCategories = newItems;

    this.impactCategories = newItems.map((item, index) => ({
      ...item,
      sort: index
    }));

    this.orderChangeSubject.next(this.impactCategories);

  }


  /**
   *  Sets up the stream that will handle order-change events and
   *  make the API call only after a short pause (debounce).
   */
  private setupDebouncedOrderChange(): void {
    this.orderChangeSubject
      .pipe(
        debounceTime(300),
        // Only trigger when the emitted array actually changes
        distinctUntilChanged(
          (prev, curr) => JSON.stringify(prev) === JSON.stringify(curr)
        ),
        // Switch to the actual API call
        switchMap((updatedItems) => {
          this.loaderService.show();
          return this.impactCategoryService.updateImpactCategoriesOrder(updatedItems)
            .pipe(
              finalize(() => this.loaderService.hide())
            );
        })
      )
      .subscribe({
        next: (res) => {
        },
        error: (err) => {
          this.toast.error(err?.error?.message);
        }
      });
  }
}
