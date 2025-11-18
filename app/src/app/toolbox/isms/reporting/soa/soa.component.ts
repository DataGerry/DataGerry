import { Component, OnInit, TemplateRef, ViewChild } from '@angular/core';
import { finalize } from 'rxjs/operators';

import { Column } from 'src/app/layout/table/table.types';
import { LoaderService } from 'src/app/core/services/loader.service';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { SoaService } from '../../services/soa.service';
import { ControlMeasure } from '../../models/control-measure.model';
import { FileExportService } from 'src/app/core/services/file-export.service';
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

  public controls: ControlMeasure[] = [];
  public loading = false;

  public columns: Column[] = [];
  public initialVisibleColumns: string[] = [];

  constructor(
    private readonly soaService: SoaService,
    private readonly loader: LoaderService,
    private readonly toast: ToastService,
    private readonly fileExportService: FileExportService,
    private readonly ismsValidationService: IsmsValidationService
  ) { }

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
   * Load the list of controls from the SOA service.
   */
  private loadControls(): void {
    this.loading = true;
    this.loader.show();

    this.soaService.getSoaList()
      .pipe(finalize(() => {
        this.loading = false;
        this.loader.hide();
      }))
      .subscribe({
        next: (resp) => {
          this.controls = resp;
        },
        error: (err) => {
          this.toast.error(err?.error?.message);
        }
      });
  }


  /**
   * Export the current controls to CSV
   */
  exportCsv(): void {
    this.fileExportService.exportCsv(
      `soa_${getCurrentDate()}`,
      this.getTransformedControls(),
      this.columnsForExport,
      this.columnHeaders
    );
  }



  /**
   * Export the current controls to XLSX
   */
  exportXlsx(): void {
    this.fileExportService.exportXlsx(
      `soa_${getCurrentDate()}`,
      this.getTransformedControls(),
      this.columnsForExport,
      this.columnHeaders
    );
  }



  /**
   * Export the current controls to PDF
   */
  exportPdf(): void {
    const filteredColumns = this.columnsForExport.filter(col => col !== 'control_measure_type');
    const filteredHeaders = { ...this.columnHeaders };
    delete filteredHeaders['control_measure_type'];
  
    this.fileExportService.exportPdf(
      `soa_${getCurrentDate()}`,
      this.getTransformedControls(),
      filteredColumns,
      filteredHeaders,
      true
    );
  }



  /**
   *  Transform the controls to match the export format.
   */
  private getTransformedControls(): any[] {
    return this.controls.map(control => ({
      ...control,
      is_applicable:
        control.is_applicable === true ? 'Yes' :
          control.is_applicable === false ? 'No' :
            ''
    }));
  }


}
