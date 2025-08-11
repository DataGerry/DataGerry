
import {
  Component, OnInit, ViewChild, TemplateRef
} from '@angular/core';
import { finalize } from 'rxjs/operators';
import { Column, Sort, SortDirection }
  from 'src/app/layout/table/table.types';

import { RiskTreatmentPlanService }
  from '../../services/risk-treatment-plan.service';
import { FileExportService } from 'src/app/core/services/file-export.service';
import { LoaderService } from 'src/app/core/services/loader.service';
import { ToastService } from 'src/app/layout/toast/toast.service';

import jsPDF from 'jspdf';
import autoTable from 'jspdf-autotable';
import { getTextColorBasedOnBackground, hexToRgb } from 'src/app/core/utils/color-utils';
import { getCurrentDate } from 'src/app/core/utils/date.utils';
import { IsmsValidationService } from '../../services/isms-validation.service';

type ApiRow = any;             // raw row from the API
type ViewRow = Record<string, any>; // flattened for table / export

@Component({
    selector: 'app-risk-treatment-plan',
    templateUrl: './risk-treatment-plan.component.html',
    standalone: false
})
export class RiskTreatmentPlanComponent implements OnInit {

  /* --------- cell templates --------- */
  @ViewChild('riskBeforeTpl', { static: true }) riskBeforeTpl!: TemplateRef<any>;
  @ViewChild('riskAfterTpl', { static: true }) riskAfterTpl!: TemplateRef<any>;
  @ViewChild('dateTpl', { static: true }) dateTpl!: TemplateRef<any>;
  @ViewChild('controlsTpl', { static: true }) controlsTpl!: TemplateRef<any>;
  @ViewChild('treatmentOptionTpl', { static: true }) treatmentOptionTpl!: TemplateRef<any>;

  /* --------- data --------- */
  rawRows: ViewRow[] = [];   // whole list
  viewRows: ViewRow[] = [];   // same list (no filtering)
  totalItems = 0;

  /* --------- UI state --------- */
  loading = false;
  page = 1;
  limit = 10;
  sort: Sort = { name: 'risk_name', order: SortDirection.ASCENDING };

  columns: Column[] = [];
  initialVisibleColumns: string[] = [];

  public isLoading$ = this.loader.isLoading$;

  /* --------- ctor --------- */
  constructor(
    private readonly api: RiskTreatmentPlanService,
    private readonly fileExp: FileExportService,
    private readonly loader: LoaderService,
    private readonly toast: ToastService,
    private readonly ismsValidationService :IsmsValidationService
    
  ) { }

  /* ================================================================
   * life-cycle
   * ============================================================= */
  ngOnInit(): void {
    this.buildColumns();

    this.ismsValidationService.checkAndHandleInvalidConfig().subscribe({
      next: (isValid) => {
        if (!isValid) return;
        this.loadData();
      },
      error: (err) => {
        this.toast.error(err?.error?.message );
      }
    })
    
  }

  /* ================================================================
   * helpers
   * ============================================================= */
  private fmtDate(d?: { year: number, month: number, day: number } | null): string {
    return d ? `${d.year}-${`${d.month}`.padStart(2, '0')}-${`${d.day}`.padStart(2, '0')}` : '';
  }

  private process(list: ApiRow[]): ViewRow[] {
    return list.map(r => ({
      ...r,
      prot_goals_str: (r.protection_goals ?? []).join(', '),
      controls_str: (r.control_measures ?? []).join(', '),
      planned_date_str: this.fmtDate(r.planned_implementation_date),
      risk_before_val: r.risk_before?.value ?? '',
      risk_after_val: r.risk_after?.value ?? ''
    }));
  }

  /* ================================================================
   * table columns
   * ============================================================= */
  private buildColumns(): void {
    this.columns = [
      { display: 'Risk Name', name: 'risk_name', data: 'risk_name', sortable: true },
      { display: 'Identifier', name: 'risk_identifier', data: 'risk_identifier', sortable: true },
      { display: 'Category', name: 'risk_category', data: 'risk_category', sortable: true },
      { display: 'Protection Goals', name: 'prot_goals_str', data: 'prot_goals_str' },

      { display: 'Object', name: 'object', data: 'object', sortable: true },
      { display: 'Object Type', name: 'object_type', data: 'object_type', sortable: true },

      { display: 'Risk Before', name: 'risk_before', data: 'risk_before', template: this.riskBeforeTpl },
      { display: 'Treatment Option', name: 'risk_treatment_option', data: 'risk_treatment_option', template: this.treatmentOptionTpl },
      { display: 'Responsible', name: 'responsible_person', data: 'responsible_person' },

      { display: 'Planned Impl. Date', name: 'planned_date_str', data: 'planned_date_str', template: this.dateTpl },

      { display: 'Risk After', name: 'risk_after', data: 'risk_after', template: this.riskAfterTpl },
      { display: 'Impl. Status', name: 'implementation_status', data: 'implementation_status' },

      { display: 'Assigned Controls', name: 'controls_str', data: 'controls_str', template: this.controlsTpl, cssClasses: ['text-center'],
      }
    ];
    this.initialVisibleColumns = this.columns.map(c => c.name);
  }

  /* ================================================================
   * data load
   * ============================================================= */
  private loadData(): void {
    this.loading = true;
    this.loader.show();

    this.api.getRiskTreatmentPlanList()
      .pipe(finalize(() => { this.loading = false; this.loader.hide(); }))
      .subscribe({
        next: (list: any[]) => {
          this.rawRows = this.process(list);
          this.applyView();         // no filter → copy + sort + page
        },
        error: err => this.toast.error(err?.error?.message ?? 'Load failed')
      });
  }

  /* copy, sort, page */
  private applyView(): void {
    let rows = [...this.rawRows];

    rows.sort((a, b) => {
      const av = String(a[this.sort.name] ?? '').toLowerCase();
      const bv = String(b[this.sort.name] ?? '').toLowerCase();
      return (av < bv ? -1 : av > bv ? 1 : 0) *
        (this.sort.order === SortDirection.ASCENDING ? 1 : -1);
    });

    this.totalItems = rows.length;
    const start = (this.page - 1) * this.limit;
    this.viewRows = rows.slice(start, start + this.limit);
  }

  /* ================================================================
   * exports
   * ============================================================= */
  private exportCols = [
    'Risk Name', 'Identifier', 'Category', 'Protection Goals',
    'Object', 'Object Type',
    'Risk Before', 'Treatment Option', 'Responsible',
    'Planned Impl. Date', 'Risk After', 'Impl. Status',
    'Control Measures'
  ];

  private exportRows() {
    return this.rawRows.map(r => ({
      'Risk Name': r.risk_name,
      'Identifier': r.risk_identifier ?? '',
      'Category': r.risk_category ?? '',
      'Protection Goals': r.prot_goals_str,
      'Object': r.object,
      'Object Type': r.object_type,
      'Risk Before': r.risk_before_val,
      'Treatment Option': r.risk_treatment_option ?? '',
      'Responsible': r.responsible_person ?? '',
      'Planned Impl. Date': r.planned_date_str,
      'Risk After': r.risk_after_val,
      'Impl. Status': r.implementation_status ?? '',
      'Control Measures': r.controls_str
    }));
  }

  exportCsv() { this.fileExp.exportCsv(`risk-treatment-plan_${getCurrentDate()}`, this.exportRows(), this.exportCols); }
  exportXlsx() { this.fileExp.exportXlsx(`risk-treatment-plan_${getCurrentDate()}`, this.exportRows(), this.exportCols); }

  // exportPdf(): void {
  //   const pdf = new jsPDF({ orientation: 'l', unit: 'pt', format: 'a4' });
  //   const rows = this.exportRows();
  //   autoTable(pdf, {
  //     head: [this.exportCols],
  //     body: rows.map(r => this.exportCols.map(k => r[k])),
  //     startY: 30,
  //     margin: { top: 30, bottom: 20, left: 20, right: 20 },
  //     styles: { fontSize: 8, cellPadding: 2, overflow: 'linebreak' },
  //     headStyles: { fontSize: 8, fillColor: [47, 102, 153], textColor: 255 },
  //     didDrawPage: ({ pageNumber }) => {
  //       pdf.setFontSize(9);
  //       pdf.text(
  //         `Page ${pageNumber} / ${pdf.getNumberOfPages()}`,
  //         pdf.internal.pageSize.getWidth() - 60,
  //         pdf.internal.pageSize.getHeight() - 10
  //       );
  //     }
  //   });
  //   pdf.save('risk-treatment-plan.pdf');
  // }

  exportPdf(): void {
    const pdf = new jsPDF({ orientation: 'l', unit: 'pt', format: 'a4' });
    const rows = this.exportRows();
  
    autoTable(pdf, {
      head: [this.exportCols],
      body: rows.map(r => this.exportCols.map(k => r[k])),
      startY: 30,
      margin: { top: 30, bottom: 20, left: 20, right: 20 },
      styles: { fontSize: 8, cellPadding: 2, overflow: 'linebreak' },
      headStyles: { fontSize: 8, fillColor: [47, 102, 153], textColor: 255 },
      didParseCell: data => {
        if (data.row.section === 'body') {
          const colName = this.exportCols[data.column.index];
          const rowIndex = data.row.index;
          const rowData = this.rawRows[rowIndex]; // Get raw row
  
          // For 'Risk Before'
          if (colName === 'Risk Before') {
            const riskObj = rowData.risk_before;
            if (riskObj?.color && riskObj?.value !== undefined) {
              const rgb = hexToRgb(riskObj.color);
              data.cell.styles.fillColor = rgb;
              data.cell.text = [String(riskObj.value)];
            }
          }
  
          // For 'Risk After'
          if (colName === 'Risk After') {
            const riskObj = rowData.risk_after;
            if (riskObj?.color && riskObj?.value !== undefined) {
              const rgb = hexToRgb(riskObj.color);
              data.cell.styles.fillColor = rgb;
              data.cell.text = [String(riskObj.value)];
            }
          }
        }
      },
      didDrawPage: ({ pageNumber }) => {
        pdf.setFontSize(9);
        pdf.text(
          `Page ${pageNumber} / ${pdf.getNumberOfPages()}`,
          pdf.internal.pageSize.getWidth() - 60,
          pdf.internal.pageSize.getHeight() - 10
        );
      }
    });
  
    pdf.save(`risk-treatment-plan_${getCurrentDate()}`);
  }
  


  /* ================================================================
   * table events
   * ============================================================= */
  onPageChange(p: number) { this.page = p; this.applyView(); }
  onPageSizeChange(l: number) { this.limit = l; this.page = 1; this.applyView(); }
  onSortChange(s: Sort) { this.sort = s; this.applyView(); }

  /* ================================================================
   * Helpers
   * ============================================================= */


  /**
   * Wrapper for getTextColorBasedOnBackground to make it accessible in the template.
   */
  public getTextColor(color: string): string {
    return getTextColorBasedOnBackground(color);
  }
}
