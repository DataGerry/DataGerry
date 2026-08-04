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
import { Component, inject, OnInit, OnDestroy, TemplateRef, ViewChild } from '@angular/core';
import { ReplaySubject } from 'rxjs';
import { finalize, takeUntil } from 'rxjs/operators';
import { CollectionParameters } from 'src/app/services/models/api-parameter';
import { APIGetMultiResponse } from 'src/app/services/models/api-response';
import { NgbModal } from '@ng-bootstrap/ng-bootstrap';
import { Sort, SortDirection } from 'src/app/layout/table/table.types';
import { AddCategoryModalComponent } from 'src/app/framework/category/components/modals/add-category-modal/add-category-modal.component';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { Router } from '@angular/router';
import { DeleteModalService } from 'src/app/core/services/delete-modal.service';
import { LoaderService } from 'src/app/core/services/loader.service';
import { ReportService } from '../../../services/report.service';

@Component({
    selector: 'app-report-overview',
    templateUrl: './report-overview.component.html',
    styleUrls: ['./report-overview.component.scss'],
    standalone: false
})
export class ReportOverviewComponent implements OnInit, OnDestroy {
  private readonly reportService = inject(ReportService);
  private readonly modalService = inject(NgbModal);
  private readonly deleteModalService = inject(DeleteModalService);
  private readonly toast = inject(ToastService);
  private readonly router = inject(Router);
  private readonly loaderService = inject(LoaderService);

  private unsubscribe$ = new ReplaySubject<void>(1);
  public reports: Array<any> = [];
  public totalReports: number = 0;
  public limit: number = 10;
  public page: number = 1;
  public loading: boolean = false;
  public sort: Sort = { name: 'public_id', order: SortDirection.ASCENDING } as Sort;
  public filter: string;
  public isLoading$ = this.loaderService.isLoading$;

  @ViewChild('actionsTemplate', { static: true }) actionsTemplate: TemplateRef<any>;

  public columns: Array<any>;

  /* --------------------------------------------------- LIFECYCLE METHODS -------------------------------------------------- */

  ngOnInit(): void {
    this.columns = [
      { display: 'ID', name: 'public_id_str', data: 'public_id', searchable: true, sortable: true, style: { width: '80px', 'text-align': 'center' } },
      { display: 'Name', name: 'name', data: 'name', searchable: true, sortable: true, style: { width: 'auto', 'text-align': 'center' } },
      { display: 'Category ID', name: 'category', data: 'report_category_id', searchable: true, sortable: true, style: { width: '150px', 'text-align': 'center' } },
      { display: 'Actions', name: 'actions', template: this.actionsTemplate, sortable: false, style: { width: '150px', 'text-align': 'center' } }
    ];

    this.loadReports();
  }


  ngOnDestroy(): void {
    this.unsubscribe$?.next();
    this.unsubscribe$?.complete();
  }

  /* --------------------------------------------------- API METHODS -------------------------------------------------- */


  /**
   * Loads reports based on the current pagination, sorting, and limit settings.
   * Updates the reports array and total reports count or logs an error if loading fails.
   */
  private loadReports(): void {
    this.loaderService.show();
    this.loading = true;
    const params: CollectionParameters = {
      filter: this.filterBuilder(),
      limit: this.limit,
      page: this.page,
      sort: this.sort.name === 'public_id_str' ? 'public_id' : this.sort.name,
      order: this.sort.order
    };

    this.reportService.getAllReports(params)
      .pipe(takeUntil(this.unsubscribe$), finalize(() => this.loaderService.hide()))
      .subscribe({
        next: (response: APIGetMultiResponse<any>) => {
          if (response && response.results) {
            this.reports = response.results;
            this.totalReports = response.total || 0;
          } else {
            this.reports = [];
            this.totalReports = 0;
          }
          this.loading = false;
        },
        error: () => {
          this.reports = [];
          this.totalReports = 0;
          this.loading = false;
        }
      });
  }

  /* --------------------------------------------------- ACTIONS -------------------------------------------------- */

  /**
   * Runs the report with the specified ID.
   * @param id - The ID of the report to run.
   */
  public runReport(report: any): void {
    if (this.hasMissingRequiredFields(report)) {
      this.toast.warning('Cannot run report - no fields selected');
      return;
    }
    const { public_id, type_id, selected_fields, mds_mode } = report;

    this.router.navigate(['/reports/run', public_id], {
      queryParams: { type_id, selected_fields: JSON.stringify(selected_fields), mds_mode }
    });
  }


  /**
   * Edits the report with the specified ID.
   * @param id - The ID of the report to edit.
   */
  public editReport(id: number): void {
    this.router.navigate(['/reports/edit', id]);
  }


  /**
   * Deletes the report with the specified public ID and reloads reports on success.
   * @param public_id - The public ID of the report to delete.
   */
  private deleteReport(public_id: number): void {
     this.loaderService.show();
    this.reportService.deleteReport(public_id)
      .pipe(takeUntil(this.unsubscribe$), finalize(() => this.loaderService.hide()))
      .subscribe({
        next: () => {
          this.toast.success('Report deleted successfully');
          this.loadReports();
        },
        error: (error) => {
          this.toast.error(error?.error?.message);
        }
      });
  }


  /**
   * Handles pagination by updating the current page and reloading reports.
   * @param newPage - The new page number to load.
   */
  public onPageChange(newPage: number): void {
    this.page = newPage;
    this.loadReports();
  }


  /**
   * Updates the sort criteria and reloads the reports.
   * @param sort - The new sort criteria.
   */
  public onSortChange(sort: Sort): void {
    this.sort = sort;
    this.loadReports();
  }


  /**
   * Handles search input changes, updates the filter, resets to the first page, and reloads reports.
   * @param search - The search input value.
   */
  public onSearchChange(search: any): void {
    if (search) {
      this.filter = search;
    } else {
      this.filter = undefined;
    }
    this.page = 1; // Reset to first page when search changes
    this.loadReports();
  }


  /**
   * Handles changes to the page size, updates the limit, resets to the first page, and reloads reports.
   * @param limit - The new number of items per page.
   */
  public onPageSizeChange(limit: number): void {
    this.limit = limit;
    this.page = 1; // Reset to first page when page size changes
    this.loadReports();
  }


  /**
   * Builds a MongoDB aggregation pipeline based on the current filter.
   * @returns An aggregation pipeline array.
   */
  private filterBuilder(): any[] {
    const query: any[] = [];

    if (this.filter) {
      const searchableColumns = this.columns.filter(c => c.searchable);
      const or: any[] = [];

      const addFields: any = {};

      for (const column of searchableColumns) {
        let fieldName = column.data || column.name;
        let searchField = fieldName;

        // Convert numeric fields to strings
        if (fieldName === 'public_id') {
          addFields['public_id_str'] = { $toString: '$public_id' };
          searchField = 'public_id_str';
        }

        if (fieldName === 'report_category_id') {
          addFields['report_category_id'] = { $toString: '$report_category_id' };
          searchField = 'report_category_id';
        }

        // Add regex condition
        const regexCondition: any = {};
        regexCondition[searchField] = {
          $regex: String(this.filter),
          $options: 'i'
        };
        or.push(regexCondition);
      }

      if (Object.keys(addFields).length > 0) {
        query.push({ $addFields: addFields });
      }

      query.push({
        $match: {
          $or: or
        }
      });
    }
    return query;
  }


  /* --------------------------------------------------- MODALS METHODS -------------------------------------------------- */


  /**
   * Opens the Add Report modal and reloads reports on successful addition.
   */
  public openAddReportModal(): void {
    const modalRef = this.modalService.open(AddCategoryModalComponent, { size: 'lg' });
    modalRef.result.then(
      (result) => {
        if (result === 'success') {
          this.loadReports();
        }
      },
      (error) => {
        this.toast.error(error?.error?.message);
      }
    );
  }

  /**
   * Opens the Delete Report modal and deletes the report if confirmed.
   * @param report - The report to delete.
   */
  public openDeleteReportModal(report: any): void {
    this.deleteModalService.confirmDelete({
      title: 'Delete Report',
      itemType: 'Report',
      itemName: report.name,
      warningMessage: 'This will delete this report and its associated data. This action cannot be undone!',
      warningIconClass: 'fas fa-exclamation-triangle',
      onConfirm: () => this.deleteReport(report.public_id)
    });
  }


  /* --------------------------------------------------- HELPER METHODS -------------------------------------------------- */

  /**
   * Returns a CSS class for invalid reports (if no selected fields).
   */
  public reportRowValidationClass = (report: any): string => {
    return !report.selected_fields?.length ? 'invalid-report-row' : '';
  };
  

  /**
   * Checks if a report has missing required fields (no selected fields).
   */
  public hasMissingRequiredFields(report: any): boolean {
    return !report.selected_fields?.length;
  }
}