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
    Component,
    inject,
    ElementRef,
    OnInit,
    ViewChild,
} from '@angular/core';
import { forkJoin } from 'rxjs';
import { finalize } from 'rxjs/operators';
import { NgbModal } from '@ng-bootstrap/ng-bootstrap';

import { jsPDF } from 'jspdf';
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
    private readonly reportSrv = inject(RiskMatrixReportService);
    private readonly impactSrv = inject(ImpactService);
    private readonly lhSrv = inject(LikelihoodService);
    private readonly rcSrv = inject(RiskClassService);
    private readonly loader = inject(LoaderService);
    private readonly toast = inject(ToastService);
    private readonly modal = inject(NgbModal);
    private readonly ismsValidationService = inject(IsmsValidationService);

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
        const ref = this.modal.open(RiskAssessmentDrilldownModalComponent, {
            size: 'xl',
            windowClass: 'dg-modal-window',
            backdropClass: 'dg-modal-window-backdrop'
        });
        ref.componentInstance.assessmentIds = ids;
    }

    /* PDF export -------------------------------------------------------------- */
    async exportPdf(): Promise<void> {

        const wrapper = this.reportContent?.nativeElement;
        const sections = wrapper?.querySelectorAll<HTMLElement>('.report-section');

        if (!wrapper || !sections?.length) {
            this.toast.error('PDF export failed');
            return;
        }

        this.loader.show();
        try {
            /* let the browser paint before the blocking capture */
            await new Promise<void>(resolve => setTimeout(resolve));

            const scale = 2;
            const wrapperRect = wrapper.getBoundingClientRect();
            const sectionRects = Array.from(sections, section => section.getBoundingClientRect());

            const snapshot = await html2canvas(wrapper, {
                backgroundColor: '#ffffff',
                scale,
                useCORS: true,
                ignoreElements: element => !this.isNeededForCapture(element, wrapper)
            });

            const pdf = new jsPDF({ orientation: 'p', unit: 'pt', format: 'a4' });

            const pageW = pdf.internal.pageSize.getWidth();
            const pageH = pdf.internal.pageSize.getHeight();
            const margin = 40;
            const gap = 24;
            const maxW = pageW - margin * 2;
            const maxH = pageH - margin * 2;

            let y = margin;

            for (const rect of sectionRects) {
                const canvas = this.cropCanvas(
                    snapshot,
                    (rect.left - wrapperRect.left) * scale,
                    (rect.top - wrapperRect.top) * scale,
                    rect.width * scale,
                    rect.height * scale
                );

                const fit = Math.min(maxW / canvas.width, maxH / canvas.height);
                const imgW = canvas.width * fit;
                const imgH = canvas.height * fit;

                if (y > margin && y + imgH > pageH - margin) {
                    pdf.addPage();
                    y = margin;
                }

                /* JPEG is embedded as-is; PNG would be decoded and stored uncompressed */
                pdf.addImage(canvas.toDataURL('image/jpeg', 0.92), 'JPEG', (pageW - imgW) / 2, y, imgW, imgH);
                y += imgH + gap;
            }

            pdf.save(`risk-matrix-report_${getCurrentDate()}`);

        } catch (err) {
            this.toast.error('PDF export failed');
        } finally {
            this.loader.hide();
        }
    }

    /* html2canvas clones the whole page; skipping unrelated nodes keeps the capture fast */
    private isNeededForCapture(element: Element, wrapper: HTMLElement): boolean {
        return element.contains(wrapper)
            || wrapper.contains(element)
            || element.closest('head') !== null
            || element instanceof HTMLStyleElement
            || element instanceof HTMLLinkElement;
    }

    private cropCanvas(source: HTMLCanvasElement, x: number, y: number,
        width: number, height: number): HTMLCanvasElement {

        const canvas = document.createElement('canvas');
        canvas.width = Math.round(width);
        canvas.height = Math.round(height);
        canvas.getContext('2d')?.drawImage(
            source, Math.round(x), Math.round(y), canvas.width, canvas.height,
            0, 0, canvas.width, canvas.height
        );
        return canvas;
    }
}
