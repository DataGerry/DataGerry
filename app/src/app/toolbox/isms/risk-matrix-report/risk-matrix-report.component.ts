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
import {
    Component, ElementRef, OnInit, ViewChild
} from '@angular/core';
import { forkJoin } from 'rxjs';
import { finalize } from 'rxjs/operators';
import { NgbModal } from '@ng-bootstrap/ng-bootstrap';

import jsPDF from 'jspdf';
import html2canvas from 'html2canvas';

import { LoaderService } from 'src/app/core/services/loader.service';
import { ToastService } from 'src/app/layout/toast/toast.service';

import { Impact } from '../models/impact.model';
import { Likelihood } from '../models/likelihood.model';
import { RiskClass } from '../models/risk-class.model';
import { ReportRiskMatrix } from '../models/risk-matrix-report.model';

import { ImpactService } from '../services/impact.service';
import { LikelihoodService } from '../services/likelihood.service';
import { RiskClassService } from '../services/risk-class.service';
import { RiskMatrixReportService } from '../services/risk-matrix-report.service';

import { RiskAssessmentDrilldownModalComponent }
    from './modal/risk-assessment-drilldown-modal.component';
import { getCurrentDate } from 'src/app/core/utils/date.utils';
import { IsmsValidationService } from '../services/isms-validation.service';

@Component({
    selector: 'app-risk-matrix-report',
    templateUrl: './risk-matrix-report.component.html',
    styleUrls: ['./risk-matrix-report.component.scss'],
    standalone: false
})
export class RiskMatrixReportComponent implements OnInit {

    /* DOM node that will be rendered to a canvas */
    @ViewChild('reportContent', { static: false })
    reportContent!: ElementRef<HTMLDivElement>;

    impacts: Impact[] = [];
    likelihoods: Likelihood[] = [];
    riskClasses: RiskClass[] = [];

    before: any[] = [];
    current: any[] = [];
    after: any[] = [];
    isLoading$ = this.loader.isLoading$;


    loading = false;
    public configurationIsValid: boolean = false; 

    constructor(
        private readonly reportSrv: RiskMatrixReportService,
        private readonly impactSrv: ImpactService,
        private readonly lhSrv: LikelihoodService,
        private readonly rcSrv: RiskClassService,
        private readonly loader: LoaderService,
        private readonly toast: ToastService,
        private readonly modal: NgbModal,
        private readonly ismsValidationService: IsmsValidationService
        
    ) { }

    /* ─────────────────────────────── */
    ngOnInit(): void { 
        
        this.ismsValidationService.checkAndHandleInvalidConfig().subscribe({
            next: (isValid) => {
             this.configurationIsValid = isValid;
              if (!isValid) return;
              this.loadAll();
            },
            error: (err) => {
              this.toast.error(err?.error?.message);
            }
          })
         }

    /* data fetch -------------------------------------------------------------- */
    private loadAll(): void {

        this.loading = true;
        this.loader.show();

        forkJoin({
            impacts: this.impactSrv.getImpacts({
                filter: '', limit: 10, page: 1,
                sort: 'calculation_basis', order: 1
            }),
            likelihoods: this.lhSrv.getLikelihoods({
                filter: '', limit: 0, page: 1,
                sort: 'calculation_basis', order: 1
            }),
            riskClasses: this.rcSrv.getRiskClasses({
                filter: '', limit: 0, page: 1,
                sort: 'sort', order: 1
            }),
            report: this.reportSrv.getReport()
        })
            .pipe(finalize(() => { this.loading = false; this.loader.hide(); }))
            .subscribe({
                next: res => this.handleData(
                    res.report,
                    res.impacts.results,
                    res.likelihoods.results,
                    res.riskClasses.results
                ),
                error: err => this.toast.error(err?.error?.message ?? 'Load failed')
            });
    }

    /* put axes in logical order and cache matrix cells */
    private handleData(mat: ReportRiskMatrix,
        imp: Impact[],
        lh: Likelihood[],
        rc: RiskClass[]): void {

        this.impacts = [...imp].sort((a, b) => a.calculation_basis - b.calculation_basis);
        this.likelihoods = [...lh].sort((a, b) => b.calculation_basis - a.calculation_basis); // top → bottom
        this.riskClasses = rc;

        this.before = mat.risk_matrix_before_treatment;
        this.current = mat.risk_matrix_current_state;
        this.after = mat.risk_matrix_after_treatment;
    }

    /* open list of assessments in a modal */
    onCell(ids: number[]): void {
        if (!ids?.length) { return; }
        const ref = this.modal.open(RiskAssessmentDrilldownModalComponent, { size: 'xl' });
        ref.componentInstance.assessmentIds = ids;
    }

    /* PDF export -------------------------------------------------------------- */
    async exportPdf(): Promise<void> {

        if (!this.reportContent) { 
            this.toast.error('PDF export failed');
            return;
        }

        this.loader.show();
        try {
            /* snapshot */
            const canvas = await html2canvas(this.reportContent.nativeElement, {
                backgroundColor: '#ffffff',
                scale: 2,
                useCORS: true
            });

            /* basic pdf setup */
            const pdf = new jsPDF({ orientation: 'p', unit: 'pt', format: 'a4' });

            /* dimensions */
            const pageW = pdf.internal.pageSize.getWidth();
            const pageH = pdf.internal.pageSize.getHeight();
            const margin = 40;                 // 40 pt on every side
            const usableWidth = pageW - margin * 2;

            const imgData = canvas.toDataURL('image/png');
            const imgProps = pdf.getImageProperties(imgData);
            const ratio = imgProps.width / imgProps.height;
            const imgH = usableWidth / ratio;

            let y = margin;                         // insertion cursor
            let remaining = imgH;

            while (remaining > 0) {
                pdf.addImage(imgData, 'PNG', margin, y, usableWidth, imgH);
                remaining -= (pageH - margin * 2);

                if (remaining > 0) {
                    pdf.addPage();
                    y = margin - pageH;                 // next slice starts at top
                }
            }

            pdf.save(`risk-matrix-report_${getCurrentDate()}`);

        } catch (err) {
            this.toast.error('PDF export failed');
        } finally {
            this.loader.hide();
        }
    }
}
