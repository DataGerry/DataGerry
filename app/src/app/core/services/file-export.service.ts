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
* along with this program. If not, see <https://www.gnu.org/licenses/>.
*/
import { Injectable } from '@angular/core';
import * as Papa from 'papaparse';
import { saveAs } from 'file-saver';
import { jsPDF } from 'jspdf';
import { autoTable } from 'jspdf-autotable';

type ExportFormat = 'csv' | 'xlsx' | 'pdf';

@Injectable({ providedIn: 'root' })
export class FileExportService {


    /**
     * Export to CSV using papaparse
     */
    exportCsv(filename: string, data: any[], columns: string[], headerMap?: Record<string, string>): void {
        const mapped = this.mapFields(data, columns);
        const renamed = this.renameHeaders(mapped, headerMap, columns);
        const csv = Papa.unparse(renamed);
        const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
        saveAs(blob, `${filename}.csv`);
    }


    /**
     * Export to XLSX using dynamic import
     */
    exportXlsx(filename: string, data: any[], columns: string[], headerMap?: Record<string, string>): void {
        const mapped = this.mapFields(data, columns);
        const renamed = this.renameHeaders(mapped, headerMap, columns);
        import('exceljs').then(async (ExcelJS) => {
            const workbook = new ExcelJS.Workbook();
            const worksheet = workbook.addWorksheet('data');
            const headers = renamed.length > 0 ? Object.keys(renamed[0]) : [];

            if (headers.length) {
                worksheet.addRow(headers);
                renamed.forEach(row => worksheet.addRow(headers.map(header => row[header])));
            }

            const excelBuffer = await workbook.xlsx.writeBuffer();
            const blob = new Blob([excelBuffer], { type: 'application/octet-stream' });
            saveAs(blob, `${filename}.xlsx`);
        });
    }


    /**
     * Export to PDF using jspdf and jspdf-autotable
     */
    exportPdf(
        filename: string,
        data: any[],
        columns: string[],
        headerMap?: Record<string, string>,
        landscape: boolean = false
    ): void {
        const orientation = landscape ? 'landscape' : 'portrait';
        const doc = new jsPDF({ orientation });

        const headers = columns.map(c => headerMap?.[c] || c);
        const body = this.mapFields(data, columns).map(row =>
            columns.map(col => row[col])
        );

        autoTable(doc, {
            head: [headers],
            body: body
        });

        doc.save(`${filename}.pdf`);
    }


    /**
     * Pick and order only specified fields
     */
    private mapFields(data: any[], columns: string[]): any[] {
        return data.map(row => {
            const mapped: any = {};
            for (const col of columns) {
                // Keep boolean values as booleans
                if (typeof row[col] === 'boolean') {
                    mapped[col] = row[col];
                } else {
                    mapped[col] = row[col] ?? '';
                }
            }
            return mapped;
        });
    }


    /**
     * Rename column headers for CSV/XLSX (optional)
     */
    private renameHeaders(data: any[], headerMap?: Record<string, string>, columns?: string[]): any[] {
        if (!headerMap) return data;
        return data.map(row => {
            const renamed: any = {};
            (columns || Object.keys(row)).forEach(key => {
                renamed[headerMap[key] || key] = row[key];
            });
            return renamed;
        });
    }
}
