import { Component, inject, OnInit, TemplateRef, ViewChild } from '@angular/core';
import { Router } from '@angular/router';
import { NgbModal } from '@ng-bootstrap/ng-bootstrap';
import { finalize } from 'rxjs/operators';

import { ToastService } from 'src/app/layout/toast/toast.service';
import { LoaderService } from 'src/app/core/services/loader.service';
import { FilterBuilderService } from 'src/app/core/services/filter-builder.service';
import { CoreDeleteConfirmationModalComponent } from 'src/app/core/components/dialog/delete-dialog/core-delete-confirmation-modal.component';

import { Column, Sort, SortDirection } from 'src/app/layout/table/table.types';
import { CollectionParameters } from 'src/app/services/models/api-parameter';
import { CmdbPersonGroup } from 'src/app/toolbox/isms/models/person-group.model';
import { PersonGroupService } from 'src/app/toolbox/isms/services/person-group.service';

@Component({
    selector: 'app-person-group-list',
    templateUrl: './person-group-list.component.html',
    styleUrls: ['./person-group-list.component.scss'],
    standalone: false
})
export class PersonGroupListComponent implements OnInit {
  @ViewChild('actionTemplate', { static: true }) actionTemplate: TemplateRef<any>;

  public personGroups: CmdbPersonGroup[] = [];
  public totalPersonGroups = 0;

  // Table config
  public page = 1;
  public limit = 10;
  public loading = false;
  public filter = '';
  public sort: Sort = { name: 'public_id', order: SortDirection.DESCENDING };
  public columns: Column[] = [];
  public initialVisibleColumns: string[] = [];

  private readonly router = inject(Router);
  private readonly toast = inject(ToastService);
  private readonly loaderService = inject(LoaderService);
  private readonly modalService = inject(NgbModal);
  private readonly filterBuilderService = inject(FilterBuilderService);
  private readonly personGroupService = inject(PersonGroupService);

  ngOnInit(): void {
    this.setupColumns();
    this.loadPersonGroups();
  }

  /**
   * Define columns for cmdb-table
   * @returns void
   */
  private setupColumns(): void {
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
        style: { 'text-align': 'center' }
      },
      {
        display: 'Email',
        name: 'email',
        data: 'email',
        searchable: true,
        sortable: false,
        style: { 'text-align': 'center' }
      },
      {
        display: 'Actions',
        name: 'actions',
        data: 'public_id',
        searchable: false,
        sortable: false,
        fixed: true,
        template: this.actionTemplate,
        style: { width: '120px', 'text-align': 'center' }
      }
    ];
    this.initialVisibleColumns = this.columns.map((c) => c.name);
  }

  /**
   * Load data from backend
   * @returns void
   */
  private loadPersonGroups(): void {
    this.loading = true;
    this.loaderService.show();

    const filterQuery = this.filterBuilderService.buildFilter(
      this.filter,
      [
        { name: 'name' },
        { name: 'email' }
      ]
    );

    const params: CollectionParameters = {
      filter: filterQuery,
      limit: this.limit,
      page: this.page,
      sort: this.sort.name,
      order: this.sort.order
    };

    this.personGroupService.getPersonGroups(params)
      .pipe(finalize(() => {
        this.loading = false;
        this.loaderService.hide();
      }))
      .subscribe({
        next: (resp) => {
          this.personGroups = resp.results;
          this.totalPersonGroups = resp.total;
        },
        error: (err) => {
          this.toast.error(err?.error?.message);
        }
      });
  }

  /**
   * Add new
   * @returns void
   */
  public onAddNew(): void {
    // Navigate to "Add" route; no data needed
    this.router.navigate(['/framework/person-groups/add']);
  }

  /**
   * Edit existing => pass record in state
   * @param item - The CmdbPersonGroup object to edit
   * @returns void
   */
  public onEdit(item: CmdbPersonGroup): void {
    this.router.navigate(['/framework/person-groups/edit'], { state: { personGroup: item } });
  }

  /**
   * View existing => pass record with mode=view
   * @param item - The CmdbPersonGroup object to view
   * @returns void
   */
  public onView(item: CmdbPersonGroup): void {
    this.router.navigate(['/framework/person-groups/edit'], {
      state: { personGroup: item, mode: 'view' }
    });
  }

  /**
   * Delete
   * @param item - The CmdbPersonGroup object to delete
   * @returns void
   */
  public onDelete(item: CmdbPersonGroup): void {
    if (!item.public_id) {
      return;
    }
    const modalRef = this.modalService.open(CoreDeleteConfirmationModalComponent, { size: 'lg' });
    modalRef.componentInstance.title = 'Delete Person Group';
    modalRef.componentInstance.item = item;
    modalRef.componentInstance.itemType = 'Person Group';
    modalRef.componentInstance.itemName = item.name;

    modalRef.result.then(
      (result) => {
        if (result === 'confirmed') {
          this.loaderService.show();
          this.personGroupService.deletePersonGroup(item.public_id!)
            .pipe(finalize(() => this.loaderService.hide()))
            .subscribe({
              next: () => {
                this.toast.success('Person Group deleted successfully.');
                this.loadPersonGroups();
              },
              error: (err) => {
                this.toast.error(err?.error?.message);
              }
            });
        }
      },
      () => { /* dismissed */ }
    );
  }

  /**
   * Pagination, sorting, search
   */
  public onPageChange(page: number): void {
    this.page = page;
    this.loadPersonGroups();
  }

  public onPageSizeChange(limit: number): void {
    this.limit = limit;
    this.page = 1;
    this.loadPersonGroups();
  }

  public onSortChange(sort: Sort): void {
    this.sort = sort;
    this.loadPersonGroups();
  }

  public onSearchChange(search: string): void {
    this.filter = search;
    this.page = 1;
    this.loadPersonGroups();
  }
}
