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
import { Component, EventEmitter, Input, Output } from '@angular/core';

import { getTextColorBasedOnBackground } from 'src/app/core/utils/color-utils';
import { Impact } from '../../models/impact.model';
import { Likelihood } from '../../models/likelihood.model';
import { RiskClass } from '../../models/risk-class.model';
import { ReportMatrixCell } from '../../models/risk-matrix-report.model';


@Component({
    selector: 'app-risk-matrix-grid',
    templateUrl: './risk-matrix-grid.component.html',
    styleUrls: ['./risk-matrix-grid.component.scss'],
    standalone: false
})
export class RiskMatrixGridComponent {

    /* ───────── inputs ───────── */
    @Input() title = '';
    @Input() impacts: Impact[] = [];
    @Input() likelihoods: Likelihood[] = [];
    @Input() cells: ReportMatrixCell[] = [];
    @Input() riskClasses: RiskClass[] = [];

    @Output() viewAssessments = new EventEmitter<number[]>();

    /* ───────── derived helpers ───────── */

    /** backend -> cell lookup */
    cell(row: number, col: number): ReportMatrixCell | undefined {
        return this.cells.find(c => c.row === row && c.column === col);
    }

    /** colour helpers */
    color(cell?: ReportMatrixCell): string {
        const rc = this.riskClasses.find(r => r.public_id === (cell?.risk_class_id ?? 0));
        return rc?.color || '#f5f5f5';
    }
    text(bg: string) { return getTextColorBasedOnBackground(bg); }

    /** display-order (= reversed) helper */
    backendRow(indexInDisplay: number): number {
        return this.likelihoods.length - 1 - indexInDisplay;
    }
    trackByIndex(idx: number, _item: any): number { return idx; }

}
