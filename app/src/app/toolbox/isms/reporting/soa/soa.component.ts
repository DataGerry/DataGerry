import { Component, inject, OnInit, TemplateRef, ViewChild } from '@angular/core';
import { Observable } from 'rxjs';
import { finalize, map } from 'rxjs/operators';

import { Column } from 'src/app/layout/table/table.types';
import { LoaderService } from 'src/app/core/services/loader.service';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { SoaService } from '../../services/soa.service';
import { ControlMeasure } from '../../models/control-measure.model';
import { FileExportService } from 'src/app/core/services/file-export.service';
import { CollectionParameters } from 'src/app/services/models/api-parameter';
import { getCurrentDate } from 'src/app/core/utils/date.utils';
import { IsmsValidationService } from '../../services/isms-validation.service';

@Component({
  selector: 'app-soa',
  templateUrl: './soa.component.html',
  standalone: false
})
export class SoaComponent implements OnInit {

  @ViewChild('applicableTpl', { static: true })
  applicableTpl: TemplateRef<any>;

  public controls: ControlMeasure[] = [];   // rows for the current page
  public loading = false;

  public page = 1;
  public limit = 10;
  public totalItems = 0;

  public columns: Column[] = [];
  public initialVisibleColumns: string[] = [];

  private readonly soaService = inject(SoaService);
  private readonly loader = inject(LoaderService);
  private readonly toast = inject(ToastService);
  private readonly fileExportService = inject(FileExportService);
  private readonly ismsValidationService = inject(IsmsValidationService);

  ngOnInit(): void {
    this.ismsValidationService.checkAndHandleInvalidConfig().subscribe({
      next: (isValid) => {
        if (!isValid) return;
        this.setupColumns();
        this.loadControls();
      },
      error: (err) => {
        this.toast.error(err?.error?.message);
      }
    })

  }


  /**
   * Setup the columns for the table
   */
  private setupColumns(): void {
    this.columns = [
      { display: 'Identifier', name: 'identifier', data: 'identifier', sortable: false, style: { 'text-align': 'center' } },
      { display: 'Name', name: 'title', data: 'title', sortable: false, cssClasses: ['text-center'], },
      { display: 'Chapter', name: 'chapter', data: 'chapter', sortable: false, cssClasses: ['text-center'], },
      {
        display: 'Applicable',
        name: 'is_applicable',
        data: 'is_applicable',
        sortable: false,
        template: this.applicableTpl,
        style: { 'text-align': 'center' }
      },
      { display: 'Reason', name: 'reason', data: 'reason', sortable: false, cssClasses: ['text-center'], },
      { display: 'State', name: 'implementation_state', data: 'implementation_state', sortable: false, style: { 'text-align': 'center' } },
      { display: 'Source', name: 'source', data: 'source', sortable: false, cssClasses: ['text-center'], }
    ];
    this.initialVisibleColumns = this.columns.map((c) => c.name);
  }


  columnsForExport = [
    'public_id',
    'identifier',
    'title',
    'chapter',
    'is_applicable',
    'reason',
    'implementation_state',
    'control_measure_type',
    'source'
  ];

  columnHeaders: Record<string, string> = {
    public_id: 'Public ID',
    identifier: 'Identifier',
    title: 'Title',
    chapter: 'Chapter',
    is_applicable: 'Applicable',
    reason: 'Reason',
    implementation_state: 'State',
    control_measure_type: 'Type',
    source: 'Source'
  };
  

  /**
   * Load the current page of controls from the SOA service.
   */
  private loadControls(): void {
    this.loading = true;
    this.loader.show();

    this.soaService.getSoaList(this.buildParams(this.limit))
      .pipe(finalize(() => {
        this.loading = false;
        this.loader.hide();
      }))
      .subscribe({
        next: (resp) => {
          this.controls = resp?.results ?? [];
          this.totalItems = resp?.total ?? this.controls.length;
        },
        error: (err) => {
          this.toast.error(err?.error?.message);
        }
      });
  }

  /**
   * Build request parameters.
   */
  private buildParams(limit: number): CollectionParameters {
    return {
      filter: '',
      limit,
      page: limit === 0 ? 1 : this.page,
      sort: 'public_id',
      order: 1
    };
  }

  /* ---------------------------------------------------- EVENTS ------------------------------------------------------ */
  onPageChange(p: number): void {
    this.page = p;
    this.loadControls();
  }

  onPageSizeChange(l: number): void {
    this.limit = l;
    this.page = 1;
    this.loadControls();
  }


  /**
   * Export the full SOA list to CSV
   */
  exportCsv(): void {
    this.runExport(rows =>
      this.fileExportService.exportCsv(
        `soa_${getCurrentDate()}`,
        this.getTransformedControls(rows),
        this.columnsForExport,
        this.columnHeaders
      ));
  }



  /**
   * Export the full SOA list to XLSX
   */
  exportXlsx(): void {
    this.runExport(rows =>
      this.fileExportService.exportXlsx(
        `soa_${getCurrentDate()}`,
        this.getTransformedControls(rows),
        this.columnsForExport,
        this.columnHeaders
      ));
  }



  /**
   * Export the full SOA list to PDF
   */
  exportPdf(): void {
    this.runExport(rows => {
      const filteredColumns = this.columnsForExport.filter(col => col !== 'control_measure_type');
      const filteredHeaders = { ...this.columnHeaders };
      delete filteredHeaders['control_measure_type'];
      this.fileExportService.exportPdf(
        `soa_${getCurrentDate()}`,
        this.getTransformedControls(rows),
        filteredColumns,
        filteredHeaders,
        true
      );
    });
  }


  /* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

  /** Fetch the complete result set (limit=0) for exports, independent of the current page. */
  private fetchAllControls(): Observable<ControlMeasure[]> {
    return this.soaService.getSoaList(this.buildParams(0))
      .pipe(map(resp => resp?.results ?? []));
  }

  private runExport(handler: (rows: ControlMeasure[]) => void): void {
    this.loader.show();
    this.fetchAllControls()
      .pipe(finalize(() => this.loader.hide()))
      .subscribe({
        next: rows => handler(rows),
        error: (err) => this.toast.error(err?.error?.message)
      });
  }


  /**
   *  Transform the controls to match the export format.
   */
  private getTransformedControls(rows: ControlMeasure[]): any[] {
    return rows.map(control => ({
      ...control,
      is_applicable:
        control.is_applicable === true ? 'Yes' :
          control.is_applicable === false ? 'No' :
            ''
    }));
  }


}
