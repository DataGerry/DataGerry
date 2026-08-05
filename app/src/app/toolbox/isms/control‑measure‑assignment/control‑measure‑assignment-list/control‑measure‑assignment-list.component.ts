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
import {
  Component,
  inject,
  Input,
  OnInit,
  OnChanges,
  SimpleChanges,
  TemplateRef,
  ViewChild,
} from '@angular/core';
import { ActivatedRoute, Router }    from '@angular/router';
import { finalize, forkJoin }        from 'rxjs';

import { Column, Sort, SortDirection } from 'src/app/layout/table/table.types';
import { CollectionParameters }        from 'src/app/services/models/api-parameter';

import { LoaderService }  from 'src/app/core/services/loader.service';
import { ToastService }   from 'src/app/layout/toast/toast.service';
import { FilterBuilderService } from 'src/app/core/services/filter-builder.service';
import { NgbModal } from '@ng-bootstrap/ng-bootstrap';
import { CoreDeleteConfirmationModalComponent }
        from 'src/app/core/components/dialog/delete-dialog/core-delete-confirmation-modal.component';

import { ControlMeasureService }    from '../../services/control-measure.service';
import { RiskAssessmentService }    from '../../services/risk-assessment.service';
import { ExtendableOptionService }  from 'src/app/toolbox/isms/services/extendable-option.service';
import { PersonService }            from '../../services/person.service';
import { PersonGroupService }       from '../../services/person-group.service';
import { ControlMeasureAssignmentService } from '../../services/control‑measure‑assignment.service';

@Component({
    selector: 'app-control-measure-assignment-list',
    templateUrl: './control-measure-assignment-list.component.html',
    styleUrls: ['./control-measure-assignment-list.component.scss'],
    standalone: false
})
export class ControlMeasureAssignmentListComponent
        implements OnInit, OnChanges {

  /* ── optional context from parent ── */
  @Input() controlMeasureId?: number;
  @Input() controlMeasureName?: string;
  @Input() riskAssesmentId?: number;
  @Input() riskAssessmentName?: string;

  /* ── action template ── */
  @ViewChild('actionTemplate', { static: true }) actionTemplate!: TemplateRef<any>;

  /* ── table state ── */
  assignments: any[] = [];
  totalAssignments = 0;
  page = 1;
  limit = 0;
  loading = false;
  filter = '';
  sort: Sort = { name: 'public_id', order: SortDirection.DESCENDING };
  columns: Column[] = [];
  initialVisibleColumns: string[] = [];

  /* ── lookup maps ── */
  private cmMap = new Map<number, string>();
  private raMap = new Map<number, string>();
  private respMap = new Map<number, string>();
  private stsMap = new Map<number, string>();
  private metaReady = false;

  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly srvAssign = inject(ControlMeasureAssignmentService);
  private readonly srvCM = inject(ControlMeasureService);
  private readonly srvRA = inject(RiskAssessmentService);
  private readonly srvStatus = inject(ExtendableOptionService);
  private readonly srvPers = inject(PersonService);
  private readonly srvPG = inject(PersonGroupService);
  private readonly loader = inject(LoaderService);
  private readonly toast = inject(ToastService);
  private readonly filterBld = inject(FilterBuilderService);
  private readonly modalService = inject(NgbModal);

  /* ────────── lifecycle ────────── */
  ngOnInit(): void {
    /* fallback: read params if not embedded */
    if (!this.riskAssesmentId && !this.controlMeasureId) {
      const r = this.route.snapshot.paramMap.get('riskAssesmentId');
      const c = this.route.snapshot.paramMap.get('cmId');
      if (r) { this.riskAssesmentId           = +r; }
      if (c) { this.controlMeasureId = +c; }
    }

    this.setupColumns();
    this.loadLookups();
  }

  ngOnChanges(ch: SimpleChanges): void {
    if ((ch['riskAssesmentId'] || ch['controlMeasureId']) && this.metaReady) {
      this.page = 1;
      this.loadAssignments();
    }
  }

  /* ────────── columns ────────── */
  private setupColumns(): void {
    this.columns = [
      { display: 'ID', name: 'public_id', data: 'public_id',
        searchable: false, sortable: false,
        style: { width: '80px', 'text-align': 'center' } },
        
        ...(!this.controlMeasureId ? [{
          display: 'Control / Measure',
          name: 'cmLabel',
          data: 'cmLabel',
          searchable: false,
          sortable: false
        }] : []),

      { display: 'Risk Assessment', name: 'raLabel', data: 'raLabel',
        searchable: false, sortable: false },

      { display: 'Responsible', name: 'responsibleName', data: 'responsibleName',
        searchable: false, sortable: false },

      { display: 'Priority', name: 'priorityLabel', data: 'priorityLabel',
        searchable: false, sortable: false,
        style: { width: '120px', 'text-align': 'center' } },

      { display: 'Implementation Status', name: 'statusLabel', data: 'statusLabel',
        searchable: false, sortable: false,
        style: { width: '160px' } },

      { display: 'Actions', name: 'actions', data: 'public_id',
        searchable: false, sortable: false, fixed: true,
        template: this.actionTemplate,
        style: { width: '120px', 'text-align': 'center' } }
    ];

    this.initialVisibleColumns = this.columns.map(c => c.name);
  }

  /* ────────── look‑ups ────────── */
  private loadLookups(): void {
    const base: CollectionParameters = {
      filter: '', limit: 0, page: 1, sort: 'public_id', order: SortDirection.ASCENDING
    };

    this.loader.show();
    forkJoin({
      cms: this.srvCM.getControlMeasures(base),
      ras: this.srvRA.getRiskAssessments(base),
      sts: this.srvStatus.getExtendableOptionsByType('IMPLEMENTATION_STATE'),
      prs: this.srvPers.getPersons(base),
      pgs: this.srvPG.getPersonGroups(base)
    })
    .pipe(finalize(() => this.loader.hide()))
    .subscribe({
      next: res => {
        res.cms.results.forEach((c: any) => this.cmMap.set(c.public_id, c.title));

        res.ras.results.forEach((ra: any) => {
          const nm = ra.risk_name || ra.risk_title || ra.name || 'Risk';
          this.raMap.set(ra.public_id, `RA #${ra.public_id} – ${nm}`);
        });

        res.sts.results.forEach((s: any) => this.stsMap.set(s.public_id, s.value));
        res.prs.results.forEach((p: any) => this.respMap.set(p.public_id, p.display_name));
        res.pgs.results.forEach((g: any) => this.respMap.set(g.public_id, g.name));

        this.metaReady = true;
        this.loadAssignments();
      },
      error: err => this.toast.error(err?.error?.message)
    });
  }

  /* ────────── data load ────────── */
  private loadAssignments(): void {
    if (!this.metaReady) { return; }

    this.loading = true; this.loader.show();

    const freeTxt = this.filter
      ? this.filterBld.buildFilter(this.filter, [{ name: 'public_id' }])
      : '';
    const ctx = this.riskAssesmentId
      ? { risk_assessment_id: this.riskAssesmentId }
      : this.controlMeasureId
        ? { control_measure_id: this.controlMeasureId }
        : '';

    const finalFilter = freeTxt && ctx ? { $and: [freeTxt, ctx] } : (freeTxt || ctx);

    const params: CollectionParameters = {
      filter: finalFilter,
      limit: this.limit,
      page: this.page,
      sort: this.sort.name,
      order: this.sort.order
    };

    this.srvAssign.getAssignments(params)
      .pipe(finalize(() => { this.loading = false; this.loader.hide(); }))
      .subscribe({
        next: resp => {
          
          this.assignments = (resp.results ?? []).map(a => ({
            ...a,
            cmLabel       : `${this.cmMap.get(a.control_measure_id) ?? 'CM'} (#${a.control_measure_id})`,
            // raLabel       : this.raMap.get(a.risk_assessment_id) ?? `RA #${a.risk_assessment_id}`,
            raLabel: a.naming?.cma_summary,
            responsibleName : this.respMap.get(a.responsible_for_implementation_id)
                              ?? a.responsible_for_implementation_id,
            priorityLabel : ({ 1: 'Low', 2: 'Medium', 3: 'High', 4: 'Very High' } as any)[a.priority] ?? '',
            statusLabel   : this.stsMap.get(a.implementation_status) ?? a.implementation_status
          }));
          this.totalAssignments = resp.total ?? this.assignments.length;
        },
        error: err => this.toast.error(err?.error?.message)
      });
  }

  /* ────────── action handlers ────────── */
  onAddNew(): void {
    if (this.riskAssesmentId) {
      this.router.navigate(
        ['/isms/risk_assessments', this.riskAssesmentId, 'control_measure_assignments', 'add'],
        { state: { riskAssesmentId: this.riskAssesmentId, riskAssessmentName: this.riskAssessmentName } }
      );
    } else if (this.controlMeasureId) {
      this.router.navigate(
        ['/isms/control_measures', this.controlMeasureId, 'control_measure_assignments', 'add'],
        { state: { controlMeasureId: this.controlMeasureId, controlMeasureName: this.controlMeasureName } }
      );
    } else {
      this.router.navigate(['/isms/control-measure-assignments/add']);
    }
  }

onView(item: any): void {
  this.router.navigate(
    ['/isms/control-measure-assignments/edit'],
    {
      state: {
        assignment: item,
        mode: 'view',
        ...(this.controlMeasureId ? {
            controlMeasureId:   this.controlMeasureId,
            controlMeasureName: this.controlMeasureName
        } : {}),
        ...(this.riskAssesmentId ? {
            riskAssesmentId:             this.riskAssesmentId,
            riskAssessmentName: this.riskAssessmentName
        } : {})
      }
    }
  );
}

onEdit(item: any): void {

  this.router.navigate(
    ['/isms/control-measure-assignments/edit'],

    {
      state: {
        assignment: item,
        mode: 'edit',
        ...(this.controlMeasureId ? {
            controlMeasureId:   this.controlMeasureId,
            controlMeasureName: this.controlMeasureName
        } : {}),
        ...(this.riskAssesmentId ? {
            riskAssesmentId:             this.riskAssesmentId,
            riskAssessmentName: this.riskAssessmentName
        } : {})
      }
    }
  );
}


  onDelete(item: any): void {
    if (!item.public_id) { return; }
    const modal = this.modalService.open(CoreDeleteConfirmationModalComponent, { size: 'lg' });
    modal.componentInstance.title    = 'Delete Assign Control';
    modal.componentInstance.item     = item;
    modal.componentInstance.itemType = 'Assign Control';
    modal.componentInstance.itemName = `#${item.public_id}`;

    modal.result.then(result => {
      if (result === 'confirmed') {
        this.loader.show();
        this.srvAssign.deleteAssignment(item.public_id)
          .pipe(finalize(() => this.loader.hide()))
          .subscribe({
            next : () => { this.toast.success('Assign Control deleted'); this.loadAssignments(); },
            error: err => this.toast.error(err?.error?.message)
          });
      }
    }, () => { /* dismissed */ });
  }

  /* ────────── table events ────────── */
  onPageChange(v: number)    { this.page = v;        this.loadAssignments(); }
  onPageSizeChange(v: number){ this.limit = v; this.page = 1; this.loadAssignments(); }
  onSortChange(s: Sort)      { this.sort = s;        this.loadAssignments(); }
  onSearchChange(q: string)  { this.filter = q; this.page = 1; this.loadAssignments(); }
}
