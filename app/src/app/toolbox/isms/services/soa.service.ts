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
import { inject, Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { ApiCallService } from 'src/app/services/api-call.service';
import { BaseApiService } from 'src/app/core/services/base-api.service';
import { ControlMeasure } from '../models/control-measure.model';
import { CollectionParameters } from 'src/app/services/models/api-parameter';
import { APIGetMultiResponse } from 'src/app/services/models/api-response';
import { ToastService } from 'src/app/layout/toast/toast.service';

import * as Papa from 'papaparse';
import { saveAs } from 'file-saver';
import { jsPDF } from 'jspdf';
import { autoTable } from 'jspdf-autotable';

@Injectable({ providedIn: 'root' })
export class SoaService extends BaseApiService<ControlMeasure> {
  public servicePrefix = 'isms/reports/soa';

  private readonly toast = inject(ToastService);

  constructor(protected api: ApiCallService) {
    super(api);
  }

  /**
   * Get a paginated SOA report.
   */
  getSoaList(params: CollectionParameters): Observable<APIGetMultiResponse<ControlMeasure>> {
    const httpParams = this.buildHttpParams(params);
    return this.handleGetRequest<APIGetMultiResponse<ControlMeasure>>(this.servicePrefix, httpParams);
  }

  /**
   * Format export data: only include selected fields in fixed order
   */
  private mapExportData(data: ControlMeasure[]): any[] {
    return data.map(item => ({
      public_id: item.public_id,
      identifier: item.identifier,
      title: item.title,
      chapter: item.chapter,
      is_applicable: item.is_applicable ? '✔' : '✖',
      reason: item.reason,
      implementation_state: item.implementation_state,
      control_measure_type: item.control_measure_type,
      source: item.source
    }));
  }

  /**
   * Export SOA list to CSV format.
   */
  exportCsv(filename: string, data: ControlMeasure[]): void {
    try {
      const exportData = this.mapExportData(data);
      const csv = Papa.unparse(exportData);
      const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
      saveAs(blob, `${filename}.csv`);
    } catch {
      this.toast.error('Failed to export the CSV file. Please try again.');
    }
  }

  /**
   * Export SOA list to XLSX format.
   */
  async exportXlsx(filename: string, data: ControlMeasure[]): Promise<void> {
    const exportData = this.mapExportData(data);
    try {
      const mod = await import('exceljs');
      // ExcelJS ships as a UMD bundle; webpack exposes it under `.default` on dynamic import
      const ExcelJS = (mod as { default?: typeof import('exceljs') }).default ?? mod;
      const workbook = new ExcelJS.Workbook();
      const worksheet = workbook.addWorksheet('data');
      const headers = exportData.length > 0 ? Object.keys(exportData[0]) : [];

      if (headers.length) {
        worksheet.addRow(headers);
        exportData.forEach(row => worksheet.addRow(headers.map(header => row[header])));
      }
      const excelBuffer = await workbook.xlsx.writeBuffer();
      const blob = new Blob([excelBuffer], { type: 'application/octet-stream' });
      saveAs(blob, `${filename}.xlsx`);
    } catch {
      this.toast.error('Failed to export the XLSX file. Please try again.');
    }
  }

  /**
   * Export SOA list to PDF format.
   */
  exportPdf(filename: string, data: ControlMeasure[]): void {
    try {
      const exportData = this.mapExportData(data);
      const tableData = exportData.map(item => [
        item.public_id,
        item.identifier,
        item.title,
        item.chapter,
        item.is_applicable,
        item.reason,
        item.implementation_state,
        item.control_measure_type,
        item.source
      ]);

      const doc = new jsPDF();
      autoTable(doc, {
        head: [[
          'Public ID', 'Identifier', 'Title', 'Chapter', 'Applicable',
          'Reason', 'State', 'Type', 'Source'
        ]],
        body: tableData
      });

      doc.save(`${filename}.pdf`);
    } catch {
      this.toast.error('Failed to export the PDF file. Please try again.');
    }
  }
}
