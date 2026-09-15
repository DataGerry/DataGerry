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
*
* You should have received a copy of the GNU Affero General Public License
* along with this program.  If not, see <https://www.gnu.org/licenses/>.
*/
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
import { PersonService } from '../../services/person.service';
import { CmdbPerson } from '../../models/person.model';

@Component({
    selector: 'app-person-list',
    templateUrl: './person-list.component.html',
    styleUrls: ['./person-list.component.scss'],
    standalone: false
})
export class PersonListComponent implements OnInit {
  @ViewChild('actionTemplate', { static: true }) actionTemplate: TemplateRef<any>;

  public persons: CmdbPerson[] = [];
  public totalPersons = 0;

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
  private readonly personService = inject(PersonService);

  
  ngOnInit(): void {
    this.setupColumns();
    this.loadPersons();
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
        display: 'Display Name',
        name: 'display_name',
        data: 'display_name',
        searchable: true,
        sortable: true,
        style: { width: '200px' }
      },
      {
        display: 'Phone',
        name: 'phone_number',
        data: 'phone_number',
        searchable: true,
        sortable: false
      },
      {
        display: 'Email',
        name: 'email',
        data: 'email',
        searchable: true,
        sortable: false
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
  private loadPersons(): void {
    this.loading = true;
    this.loaderService.show();

    const filterQuery = this.filterBuilderService.buildFilter(
      this.filter,
      [
        { name: 'display_name' },
        { name: 'phone_number' },
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

    this.personService.getPersons(params)
      .pipe(finalize(() => {
        this.loading = false;
        this.loaderService.hide();
      }))
      .subscribe({
        next: (resp) => {
          this.persons = resp.results;
          this.totalPersons = resp.total;
        },
        error: (err) => {
          this.toast.error(err?.error?.message);
        }
      });
  }


  /**
  * Add new person
  * @returns void
  */
  public onAddNew(): void {
    this.router.navigate(['/framework/persons/add']);
  }


  /**
   * Edit person
   * @param item - The person to edit
   * @returns void
   */
  public onEdit(item: CmdbPerson): void {
    this.router.navigate(['/framework/persons/edit'], { state: { person: item } });
  }


  /**
   * View person
   * @param item - The person to view
   * @returns void
   */
  public onView(item: CmdbPerson): void {
    this.router.navigate(['/framework/persons/view'], {
      state: { person: item, mode: 'view' }
    });
  }


  /**
   * Delete person
   * @param item - The person to delete
   * @returns void
   */
  public onDelete(item: CmdbPerson): void {
    if (!item.public_id) {
      return;
    }
    const modalRef = this.modalService.open(CoreDeleteConfirmationModalComponent, {
      size: 'lg',
      windowClass: 'dg-modal-window',
      backdropClass: 'dg-modal-window-backdrop'
    });
    modalRef.componentInstance.title = 'Delete Person';
    modalRef.componentInstance.item = item;
    modalRef.componentInstance.itemType = 'Person';
    modalRef.componentInstance.itemName = item.display_name;

    modalRef.result.then(
      (result) => {
        if (result === 'confirmed') {
          this.loaderService.show();
          this.personService.deletePerson(item.public_id!)
            .pipe(finalize(() => this.loaderService.hide()))
            .subscribe({
              next: () => {
                this.toast.success('Person deleted successfully.');
                this.loadPersons();
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
    this.loadPersons();
  }

  public onPageSizeChange(limit: number): void {
    this.limit = limit;
    this.page = 1;
    this.loadPersons();
  }

  public onSortChange(sort: Sort): void {
    this.sort = sort;
    this.loadPersons();
  }

  public onSearchChange(search: string): void {
    this.filter = search;
    this.page = 1;
    this.loadPersons();
  }
}
