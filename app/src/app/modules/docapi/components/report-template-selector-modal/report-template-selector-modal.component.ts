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
<<<<<<< HEAD
import { Component, EventEmitter, Output, OnDestroy, OnInit } from '@angular/core';
=======
import { Component, inject, EventEmitter, Output, OnDestroy, OnInit } from '@angular/core';
>>>>>>> origin/version-3.2
import { NgbActiveModal } from '@ng-bootstrap/ng-bootstrap';
import { finalize, Subject, takeUntil } from 'rxjs';
import { LoaderService } from 'src/app/core/services/loader.service';
import { APIGetMultiResponse } from 'src/app/services/models/api-response';
import { CollectionParameters } from 'src/app/services/models/api-parameter';
import { ReportService } from 'src/app/toolbox/reporting/services/report.service';

@Component({
  selector: 'cmdb-report-template-selector-modal',
  templateUrl: './report-template-selector-modal.component.html',
  styleUrls: ['./report-template-selector-modal.component.scss'],
  standalone: false
})
export class ReportTemplateSelectorModalComponent implements OnInit, OnDestroy {
<<<<<<< HEAD
=======
  public readonly activeModal = inject(NgbActiveModal);
  private readonly reportService = inject(ReportService);
  private readonly loaderService = inject(LoaderService);

>>>>>>> origin/version-3.2
  @Output() insertTemplate = new EventEmitter<string>();

  public reports: Array<any> = [];
  public selectedReportId: number | null = null;
  public previewTemplate = '';
  public loadingReports = false;
  public isLoading$ = this.loaderService.isLoading$;
  public selectedReport: any = null;

  private destroy$ = new Subject<void>();

<<<<<<< HEAD
  constructor(
    public activeModal: NgbActiveModal,
    private reportService: ReportService,
    private loaderService: LoaderService
  ) {}

=======
>>>>>>> origin/version-3.2
  ngOnInit(): void {
    this.loadReports();
  }

  ngOnDestroy(): void {
    this.destroy$?.next();
    this.destroy$?.complete();
  }

  public onReportSelected(selection: any): void {
    const reportId = typeof selection === 'number' ? selection : selection?.public_id;
    if (!reportId) {
      this.selectedReportId = null;
      this.previewTemplate = '';
      this.selectedReport = null;
      return;
    }

    this.selectedReportId = reportId;
    this.previewTemplate = this.buildTemplate(reportId);
    this.selectedReport = typeof selection === 'number'
      ? this.reports.find((report) => report?.public_id === reportId)
      : selection;
  }

  public insert(): void {
    if (!this.previewTemplate) {
      return;
    }

    this.insertTemplate.emit(this.previewTemplate);
    this.activeModal.close(this.previewTemplate);
  }

  public cancel(): void {
    this.activeModal.dismiss();
  }

  private loadReports(): void {
    const params: CollectionParameters = {
      filter: '',
      limit: 0,
      sort: 'public_id',
      order: 1,
      page: 1
    };

    this.loadingReports = true;
    this.loaderService.show();

    this.reportService
      .getAllReports(params)
      .pipe(
        takeUntil(this.destroy$),
        finalize(() => {
          this.loadingReports = false;
          this.loaderService.hide();
        })
      )
      .subscribe({
        next: (response: APIGetMultiResponse<any>) => {
          this.reports = response?.results || [];
        },
        error: () => {
          this.reports = [];
        }
      });
  }

  private buildTemplate(reportId: number): string {
    return `{{ report(${reportId}) }}`;
  }
}
