import { Component, OnInit, TemplateRef, ViewChild } from '@angular/core';
import { Router } from '@angular/router';
import { finalize } from 'rxjs/operators';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { LoaderService } from 'src/app/core/services/loader.service';
import { CollectionParameters } from 'src/app/services/models/api-parameter';
import { ExtendableOption, ObjectGroup } from '../models/object-group.model';
import { ObjectGroupService } from '../services/object-group.service';
import { Column, Sort, SortDirection } from 'src/app/layout/table/table.types';
import { NgbModal } from '@ng-bootstrap/ng-bootstrap';
import { CoreDeleteConfirmationModalComponent } from 'src/app/core/components/dialog/delete-dialog/core-delete-confirmation-modal.component';
import { ExtendableOptionService } from 'src/app/toolbox/isms/services/extendable-option.service';
import { OptionType } from 'src/app/toolbox/isms/models/option-type.enum';
import { FilterBuilderService } from 'src/app/core/services/filter-builder.service';

@Component({
    selector: 'app-object-groups-list',
    templateUrl: './object-groups-list.component.html',
    styleUrls: ['./object-groups-list.component.scss'],
    standalone: false
})
export class ObjectGroupsListComponent implements OnInit {
  @ViewChild('actionTemplate', { static: true }) actionTemplate: TemplateRef<any>;
  @ViewChild('categoriesTemplate', { static: true }) categoriesTemplate: TemplateRef<any>;

  public objectGroups: ObjectGroup[] = [];
  public totalObjectGroups = 0;
  public page = 1;
  public limit = 10;
  public loading = false;
  public filter: string;
  public sort: Sort = { name: 'public_id', order: SortDirection.ASCENDING };

  // Define table columns
  public columns: Column[] = [];
  public initialVisibleColumns: string[] = [];
  public categoryOptions: ExtendableOption[] = [];
  public isLoading$ = this.loaderService.isLoading$;

  private searchableFields = [
    { name: 'public_id' },
    { name: 'name' },
    { name: 'categories', isArray: true },
    { name: 'group_type' }
  ];

  constructor(
    private objectGroupService: ObjectGroupService,
    private toast: ToastService,
    private loaderService: LoaderService,
    private router: Router,
    private modalService: NgbModal,
    private extendableOptionService: ExtendableOptionService,
    private filterBuilderService: FilterBuilderService

  ) { }

  ngOnInit(): void {
    this.setupColumns();
    this.loadObjectGroups();
  }

  
  /**
   * Setup columns for the table
   * @returns void  
   */
  setupColumns(): void {
    this.columns = [
      {
        display: 'Public ID',
        name: 'public_id',
        data: 'public_id',
        searchable: false,
        sortable: true,
        style: { width: '120px', 'text-align': 'center' }
      },
      {
        display: 'Name',
        name: 'name',
        data: 'name',
        searchable: true,
        sortable: true,
        style: { width: 'auto', 'text-align': 'center' }

      },
      {
        display: 'Categories',
        name: 'categories',
        data: 'categories',
        searchable: true,
        sortable: false,
        template: this.categoriesTemplate,
        style: { width: 'auto', 'text-align': 'center' }
      },
      {
        display: 'Group Type',
        name: 'group_type',
        data: 'group_type',
        searchable: true,
        sortable: true,
        style: { width: '150px', 'text-align': 'center' }

      },
      {
        display: 'Actions',
        name: 'actions',
        data: 'public_id',
        searchable: false,
        sortable: false,
        fixed: true,
        template: this.actionTemplate,
        style: { width: '80px', 'text-align': 'center' }
      }
    ];
    this.initialVisibleColumns = this.columns.filter(c => !c.hidden).map(c => c.name);
  }


  /**
   * Load object groups
   * @returns void  
   */
  loadObjectGroups(): void {
    this.loading = true;
    this.loaderService.show();

    const filterQuery = this.filterBuilderService.buildFilter(this.filter, this.searchableFields);
    const params: CollectionParameters = {
      filter: filterQuery,
      limit: this.limit,
      page: this.page,
      sort: this.sort.name,
      order: this.sort.order
    };

    this.objectGroupService.getObjectGroups(params)
      .pipe(finalize(() => {
        this.loading = false;
        this.loaderService.hide();
      }))
      .subscribe({
        next: (resp) => {
          this.objectGroups = resp.results;
          this.totalObjectGroups = resp.total;
          this.loadCategories();
        },
        error: (err) => {
          this.toast.error(err?.error?.message);
        }
      });
  }


  /**
   * Load categories for the object groups
   * @returns void  
   */
  private loadCategories(): void {
    this.loaderService.show();
    this.extendableOptionService.getExtendableOptionsByType(OptionType.OBJECT_GROUP)
      .pipe((finalize(() => this.loaderService.hide())))
      .subscribe({
        next: (res) => {
          this.categoryOptions = res.results;
        },
        error: (err) => this.toast.error(err?.error?.message)
      });
  }


  /**
  * Add new object group
  * @returns void  
  */
  onAddNew(): void {
    this.router.navigate(['/framework/object_groups/add']);
  }

  /**
   * view object group
   * @param group
   * @returns void  
   */
  onView(group: ObjectGroup): void {
    this.router.navigate(['framework/object_groups/view', group.public_id], {
      state: { group, isViewMode: true }
    });
  }
  
    /**
   * Edit object group
   * @param group
   * @returns void  
   */
  onEdit(group: ObjectGroup): void {
    this.router.navigate(['framework/object_groups/edit', group.public_id], {
      state: { group, isViewMode: false }
    });
  }
  


  /**
   * Delete object group
   * @param item
   * @returns void  
   */
  public onDelete(item: ObjectGroup): void {
    const modalRef = this.modalService.open(CoreDeleteConfirmationModalComponent, { size: 'lg' });
    modalRef.componentInstance.title = 'Delete Object Group';
    modalRef.componentInstance.item = item;
    modalRef.componentInstance.itemType = 'Object Group';
    modalRef.componentInstance.itemName = item.name;

    modalRef.result.then(
      (result) => {
        if (result === 'confirmed') {
          this.loaderService.show();
          this.objectGroupService
            .deleteObjectGroup(item.public_id!)
            .pipe(finalize(() => this.loaderService.hide()))
            .subscribe({
              next: () => {
                this.toast.success('Object Group deleted successfully.');
                this.loadObjectGroups();
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
   * Pagination
   * @param page
   * @returns void  
   */
  onPageChange(page: number): void {
    this.page = page;
    this.loadObjectGroups();
  }


  /**
   * Pagination
   * @param limit
   * @returns void  
   */
  onPageSizeChange(limit: number): void {
    this.limit = limit;
    this.page = 1;
    this.loadObjectGroups();
  }


  /**
   * Sort
   * @param sort
   * @returns void  
   */
  onSortChange(sort: Sort): void {
    this.sort = sort;
    this.loadObjectGroups();
  }


  /**
   * Search
   * @param search
   * @returns void  
   */
  onSearchChange(search: string): void {
    this.filter = search;
    this.page = 1;
    this.loadObjectGroups();
  }


  /**
   * Load categories for the object groups
   * @returns void  
   */
  public getCategoryNames(categoryIds: number[]): string {

    const names = categoryIds.map(id => {
      const option = this.categoryOptions?.find(opt => opt?.public_id === id);
      return option?.value;
    });
    return names.join(', ');
  }
}
