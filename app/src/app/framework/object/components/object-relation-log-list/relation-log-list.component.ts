import {
  Component,
  inject,
  Input,
  OnInit,
  OnChanges,
  SimpleChanges,
  ViewChild,
  TemplateRef,
} from '@angular/core';
import { NgbModal } from '@ng-bootstrap/ng-bootstrap';
import { finalize, ReplaySubject, takeUntil } from 'rxjs';

import { RelationLogService, RelationLog } from 'src/app/framework/services/relation-log.service';
import { Column, Sort, SortDirection } from 'src/app/layout/table/table.types';
import { CollectionParameters } from 'src/app/services/models/api-parameter';
import { APIGetMultiResponse } from 'src/app/services/models/api-response';
import { LoaderService } from 'src/app/core/services/loader.service';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { CoreDeleteConfirmationModalComponent } from 'src/app/core/components/dialog/delete-dialog/core-delete-confirmation-modal.component';

@Component({
    selector: 'relation-log-list',
    templateUrl: './relation-log-list.component.html',
    styleUrls: ['./relation-log-list.component.scss'],
    standalone: false
})
export class RelationLogListComponent implements OnInit, OnChanges {
  private readonly relationLogService = inject(RelationLogService);
  private readonly loaderService = inject(LoaderService);
  private readonly toast = inject(ToastService);
  private readonly modalService = inject(NgbModal);

  @Input() publicID: number;

  // Table column templates
  @ViewChild('publicIdTemplate', { static: true }) publicIdTemplate: TemplateRef<any>;
  @ViewChild('logTimeTemplate', { static: true }) logTimeTemplate: TemplateRef<any>;
  @ViewChild('actionTemplate', { static: true }) actionTemplate: TemplateRef<any>;
  @ViewChild('authorTemplate', { static: true }) authorTemplate: TemplateRef<any>;
  @ViewChild('actionsTemplate', { static: true }) actionsTemplate: TemplateRef<any>;

  // Data & columns for the cmdb-table
  public logs: RelationLog[] = [];
  public columns: Column[];

  // Pagination, sorting
  public totalLogs = 0;
  public limit = 10;
  public page = 1;
  public sort: Sort = { name: 'log_time', order: SortDirection.DESCENDING };

  // Loading and search
  public loading = false;
  public filter: string;
  public isLoading$ = this.loaderService.isLoading$;

  // "View Changes" popup
  public showChangesModal = false;
  public selectedLog: RelationLog | null = null;

  private unsubscribe$ = new ReplaySubject<void>(1);

  ngOnInit(): void {
    this.setupColumns();
  }

  ngOnChanges(changes: SimpleChanges): void {
    if (changes.publicID && this.isValidID(changes.publicID.currentValue)) {
      this.loadLogs();
    }
  }

  /** If the user sets a new ID at runtime, we check if it's valid (> 0). */
  private isValidID(id: number): boolean {
    return typeof id === 'number' && id > 0;
  }

  /**
   * Define columns for the table:
   *   - Public ID
   *   - Log Time
   *   - Action
   *   - Author
   *   - A combined "Actions" column for "View" and "Delete"
   */
  private setupColumns(): void {
    this.columns = [
      {
        display: 'Public ID',
        name: 'public_id',
        data: 'public_id',
        searchable: true,
        sortable: true,
        template: this.publicIdTemplate,
        style: { width: '120px', 'text-align': 'center' }
      },
      {
        display: 'Log Time',
        name: 'log_time',
        data: 'log_time',
        searchable: false,
        sortable: true,
        template: this.logTimeTemplate,
        style: { width: 'auto', 'text-align': 'center' }
      },
      {
        display: 'Action',
        name: 'action',
        data: 'action',
        searchable: false,
        sortable: true,
        template: this.actionTemplate,
        style: { width: '120px', 'text-align': 'center' }
      },
      {
        display: 'Author',
        name: 'author_name',
        data: 'author_name',
        searchable: false,
        sortable: true,
        template: this.authorTemplate,
        style: { width: '120px', 'text-align': 'center' }
      },
      {
        display: 'Actions',
        name: 'actions',
        data: '',
        searchable: false,
        sortable: false,
        template: this.actionsTemplate,
        style: { width: '120px', 'text-align': 'center' }
      }
    ];
  }

  /**
   * Load logs from relationLogService, applying the filter for logs
   * whose "object_relation_parent_id" == publicID OR "object_relation_child_id" == publicID,
   * plus search, pagination, sorting, etc.
   */
  private loadLogs(): void {
    if (!this.isValidID(this.publicID)) return;

    // Show global loader popup
    this.loaderService.show();
    this.loading = true;

    const params: CollectionParameters = {
      filter: this.filterBuilder(),
      limit: this.limit,
      page: this.page,
      sort: this.sort.name,
      order: this.sort.order
    };

    this.relationLogService.getLogsAll(params)
      .pipe(takeUntil(this.unsubscribe$), finalize(() => this.loaderService.hide()))
      .subscribe({
        next: (response: APIGetMultiResponse<RelationLog>) => {
          this.handleLogsResponse(response);
        },
        error: (err) => {
          this.handleLogsError(err);
        }
      });
  }

  /**
   * Build the pipeline for search + $match:
   */
  private filterBuilder(): any[] {
    const filterPipeline: any[] = [];

    // Always match logs for this objectID
    const orIDClause = {
      $or: [
        { object_relation_parent_id: this.publicID },
        { object_relation_child_id: this.publicID }
      ]
    };
    filterPipeline.push({ $match: orIDClause });

    // If user typed a search term, build a $match for each searchable column
    if (this.filter) {
      const searchableColumns = this.columns.filter(col => col.searchable);
      const orConds: any[] = [];
      const addFieldsObj: any = {};

      for (const col of searchableColumns) {
        const fieldName = col.data || col.name; 
        const searchField = fieldName;

        const regexCond: any = {};
        regexCond[searchField] = { $regex: String(this.filter), $options: 'i' };
        orConds.push(regexCond);
      }

      // If we had to $addFields, we'd do it here:
      if (Object.keys(addFieldsObj).length > 0) {
        filterPipeline.push({ $addFields: addFieldsObj });
      }

      if (orConds.length > 0) {
        filterPipeline.push({ $match: { $or: orConds } });
      }
    }

    return filterPipeline;
  }

  /**
   * On successful logs fetch, rename creation_time -> log_time
   * and update table data + total count.
   */
  private handleLogsResponse(resp: APIGetMultiResponse<RelationLog>): void {
    const rawLogs = resp.results || [];
    this.totalLogs = resp.total || rawLogs.length;

    this.logs = rawLogs.map((log) => ({
      ...log,
      log_time: log.creation_time ?? log.log_time
    }));

    this.loading = false;
  }

  /**
   * On error, clear table data, reset total, show an error
   */
  private handleLogsError(err: any): void {
    this.toast.error(err?.error?.message);
    this.logs = [];
    this.totalLogs = 0;
    this.loading = false;
  }

  /**
   * Table events: pageChange, pageSizeChange, sortChange, searchChange
   */
  public onPageChange(newPage: number): void {
    this.page = newPage;
    this.loadLogs();
  }

  public onPageSizeChange(newLimit: number): void {
    this.limit = newLimit;
    this.page = 1;
    this.loadLogs();
  }

  public onSortChange(sort: Sort): void {
    this.sort = sort;
    this.loadLogs();
  }

  /**
   * If we had search enabled in the table:
   * (searchChange)="onSearchChange($event)"
   */
  public onSearchChange(searchTerm: string): void {
    this.filter = searchTerm && searchTerm.trim() ? searchTerm.trim() : undefined;
    this.page = 1;
    this.loadLogs();
  }

  /**
   * "View" button: open popup to see changes
   */
  public onViewClick(log: RelationLog): void {
    this.selectedLog = log;
    this.showChangesModal = true;
  }

  /**
   * Closes the changes popup
   */
  public closeChangesModal(): void {
    this.selectedLog = null;
    this.showChangesModal = false;
  }

  /**
   * "Delete" button: show a delete confirmation modal
   */
  public onDeleteLog(log: RelationLog): void {
    const modalRef = this.modalService.open(CoreDeleteConfirmationModalComponent, {
      size: 'lg',
      windowClass: 'dg-modal-window',
      backdropClass: 'dg-modal-window-backdrop'
    });
    modalRef.componentInstance.title = `Delete Relation Log: ${log.public_id}`;
    modalRef.componentInstance.item = log;
    modalRef.componentInstance.itemType = 'Relation Log';
    modalRef.componentInstance.itemName = log.public_id;

    modalRef.result.then(
      (result) => {
        if (result === 'confirmed') {
          this.deleteLog(log.public_id);
        }
      },
      () => {}
    );
  }

  /**
   * Actually delete the log, then reload
   */
  private deleteLog(publicId: number): void {
    this.loaderService.show();
    this.loading = true;

    this.relationLogService.deleteLog(publicId)
      .pipe(takeUntil(this.unsubscribe$), finalize(() => this.loaderService.hide()))
      .subscribe({
        next: () => {
          this.toast.success('Relation log deleted successfully');
          this.loadLogs();
        },
        error: (err) => {
          this.toast.error(err?.error?.message);
          this.loading = false;
        }
      });
  }
}
