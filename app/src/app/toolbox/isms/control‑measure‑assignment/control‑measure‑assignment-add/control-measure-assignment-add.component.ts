/*
* DATAGERRY - OpenSource Enterprise CMDB
* Copyright (C) 2025 becon GmbH
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
import { Component, Input, OnInit, inject } from '@angular/core';
import { FormBuilder, FormGroup, Validators } from '@angular/forms';
import { ActivatedRoute } from '@angular/router';
import { finalize, forkJoin } from 'rxjs';
import { Location } from '@angular/common';

import { LoaderService } from 'src/app/core/services/loader.service';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { CollectionParameters } from 'src/app/services/models/api-parameter';
import { SortDirection } from 'src/app/layout/table/table.types';

import { ControlMeasureAssignment } from '../../models/control‑measure‑assignment.model';
import { ControlMeasureAssignmentService } from '../../services/control‑measure‑assignment.service';
import { ControlMeasureService } from '../../services/control-measure.service';
import { RiskAssessmentService } from '../../services/risk-assessment.service';
import { ExtendableOptionService } from 'src/app/toolbox/isms/services/extendable-option.service';
import { PersonService } from '../../services/person.service';
import { PersonGroupService } from '../../services/person-group.service';
import { IsmsValidationService } from '../../services/isms-validation.service';

@Component({
    selector: 'app-control-measure-assignment-add',
    templateUrl: './control-measure-assignment-add.component.html',
    styleUrls: ['./control-measure-assignment-add.component.scss'],
    standalone: false
})
export class ControlMeasureAssignmentAddComponent implements OnInit {

  /* ───── context arriving from parent list (optional) ───── */
  @Input() controlMeasureId?: number;
  @Input() controlMeasureName?: string;
  @Input() riskAssesmentId?: number;
  @Input() riskAssessmentName?: string;

  /* ───── DI ───── */
  private readonly fb = inject(FormBuilder);
  private readonly route = inject(ActivatedRoute);
  private readonly loader = inject(LoaderService);
  private readonly toast = inject(ToastService);
  private readonly loc = inject(Location);

  private readonly srvAssign = inject(ControlMeasureAssignmentService);
  private readonly srvCM = inject(ControlMeasureService);
  private readonly srvRA = inject(RiskAssessmentService);
  private readonly srvExtOpt = inject(ExtendableOptionService);
  private readonly srvPer = inject(PersonService);
  private readonly srvPg = inject(PersonGroupService);
  private readonly ismsValidationService = inject(IsmsValidationService);
  private readonly location = inject(Location);

  /* ───── UI state ───── */
  form!: FormGroup;
  isSaving = false;
  isLoading$ = this.loader.isLoading$;

  isEditMode = false;
  isViewMode = false;
  private assignmentId?: number;

  /* ───── look‑ups ───── */
  cmOptions: { public_id: number; title: string }[] = [];
  raOptions: { public_id: number; label: string }[] = [];
  statusOptions: { public_id: number; value: string }[] = [];
  respOptions: { public_id: number; display_name: string; group: string; type: 'PERSON' | 'PERSON_GROUP' }[] = [];

  readonly priorityOptions = [
    { label: 'Low', value: 1 },
    { label: 'Medium', value: 2 },
    { label: 'High', value: 3 },
    { label: 'Very High', value: 4 }
  ];

  /* ───── consolidated context (single source of truth) ───── */
  private ctx = {
    cmId: 0,
    cmName: '',
    raId: 0,
    raName: ''
  };

  /* ────────── helpers used in template ────────── */
  getCMTitle(id: number | null): string {
    if (!id) { return ''; }
    if (id === this.ctx.cmId && this.ctx.cmName) { return this.ctx.cmName; }
    const found = this.cmOptions.find(o => o.public_id === id);
    return found ? found.title : `#${id}`;
  }

  getRALabel(id: number | null): string {
    if (!id) { return ''; }
    if (id === this.ctx.raId && this.ctx.raName) { return `#${id} – ${this.ctx.raName}`; }
    const found = this.raOptions.find(o => o.public_id === id);
    return found ? found.label : `#${id}`;
  }

  /* ────────── lifecycle ────────── */
  ngOnInit(): void {

    this.ismsValidationService.checkAndHandleInvalidConfig().subscribe({
      next: (isValid) => {
        if (!isValid) return;


        /* ---------- detect current mode ---------- */
        const st = history.state as any;
        this.isEditMode = st.mode === 'edit';
        this.isViewMode = st.mode === 'view';
        const incoming: ControlMeasureAssignment | undefined = st.assignment;
        if (incoming) { this.assignmentId = incoming.public_id; }

        /* ---------- consolidate context ---------- */
        /* 1/ inputs */
        if (this.controlMeasureId) { this.ctx.cmId = this.controlMeasureId; }
        if (this.controlMeasureName) { this.ctx.cmName = this.controlMeasureName; }
        if (this.riskAssesmentId) { this.ctx.raId = this.riskAssesmentId; }
        if (this.riskAssessmentName) { this.ctx.raName = this.riskAssessmentName; }

        /* 2/ navigation‑state */
        if (st.controlMeasureId) { this.ctx.cmId = st.controlMeasureId; }
        if (st.controlMeasureName) { this.ctx.cmName = st.controlMeasureName; }
        if (st.riskAssesmentId) { this.ctx.raId = st.riskAssesmentId; }
        if (st.riskAssessmentName) { this.ctx.raName = st.riskAssessmentName; }

        /* 3/ url params */
        const cmParam = this.route.snapshot.paramMap.get('cmId');
        const raParam = this.route.snapshot.paramMap.get('riskId');
        if (cmParam) { this.ctx.cmId = +cmParam; }
        if (raParam) { this.ctx.raId = +raParam; }

        /* ---------- form ---------- */
        this.buildForm();
        if (incoming) { this.form.patchValue(incoming, { emitEvent: false }); }

        /* ---------- look‑ups ---------- */
        this.loadLookups(incoming);

      },
      error: (err) => {
        this.toast.error('Failed to validate ISMS configuration. Please try again later.');
        this.location.back();
      }
    });



  }

  /* ────────── form factory ────────── */
  private buildForm(): void {
    this.form = this.fb.group({
      control_measure_id: [null, Validators.required],
      risk_assessment_id: [null, Validators.required],
      planned_implementation_date: null,
      implementation_status: [null, Validators.required],
      finished_implementation_date: null,
      priority: null,
      responsible_for_implementation_id_ref_type: ['PERSON'],
      responsible_for_implementation_id: [null, Validators.required]
    });
  }

  /* ────────── look‑ups & contextual defaults ────────── */
  private loadLookups(prePatch?: ControlMeasureAssignment): void {

    const base: CollectionParameters = {
      filter: '', limit: 0, page: 1, sort: 'public_id', order: SortDirection.ASCENDING
    };

    const requests: Record<string, any> = {
      sts: this.srvExtOpt.getExtendableOptionsByType('IMPLEMENTATION_STATE'),
      prs: this.srvPer.getPersons(base),
      pgs: this.srvPg.getPersonGroups(base)
    };
    if (!this.ctx.cmId) { requests.cms = this.srvCM.getControlMeasures(base); }
    if (!this.ctx.raId) { requests.ras = this.srvRA.getRiskAssessments(base); }

    this.loader.show();
    forkJoin(requests)
      .pipe(finalize(() => this.loader.hide()))
      .subscribe({
        next: (res: any) => {

          /* ----- Control / Measure options ----- */
          if (res.cms) {
            this.cmOptions = res.cms.results
              .map((c: any) => ({ public_id: c.public_id, title: c.title }));
          }
          if (this.ctx.cmId &&
            !this.cmOptions.some(o => o.public_id === this.ctx.cmId)) {
            this.cmOptions.unshift({
              public_id: this.ctx.cmId,
              title: this.ctx.cmName || `#${this.ctx.cmId}`
            });
          }

          // if (res.ras) {
          //   this.raOptions = res.ras.results
          //     .map((ra: any) => ({
          //       public_id: ra.public_id,
          //       label: `#${ra.public_id} – ${(ra.risk_name || ra.risk_title || ra.name || 'Risk')}`
          //     }));
          // }

          if (res.ras) {
            this.raOptions = res.ras.results.map((ra: any) => {
              const riskName = ra.naming?.risk_id_name || (ra.risk_name || ra.risk_title || ra.name || 'Risk');
              const objectSummary = ra.naming?.object_id_name;
              let label = `#${ra.public_id} - ${riskName}`;
              if (objectSummary) {
                label += ` @ ${objectSummary}`;
              }
              return { public_id: ra.public_id, label };
            });
          }
          if (this.ctx.raId &&
            !this.raOptions.some(o => o.public_id === this.ctx.raId)) {
            this.raOptions.unshift({
              public_id: this.ctx.raId,
              label: `#${this.ctx.raId} – ${this.ctx.raName || 'Risk'}`
            });
          }

          /* ----- Implementation‑status & Responsible ----- */
          this.statusOptions = res.sts.results;
          this.respOptions = [
            ...res.pgs.results.map((g: any) => ({
              public_id: g.public_id,
              display_name: g.name,
              group: 'Groups',
              type: 'PERSON_GROUP' as const
            })),
            ...res.prs.results.map((p: any) => ({
              public_id: p.public_id,
              display_name: p.display_name,
              group: 'Persons',
              type: 'PERSON' as const
            }))
          ];


          /* ----- contextual defaults / readonly ----- */
          const cmControl = this.form.get('control_measure_id');
          const raControl = this.form.get('risk_assessment_id');

          if (this.ctx.cmId && cmControl) {
            cmControl.setValue(this.ctx.cmId, { emitEvent: false });
            cmControl.disable({ emitEvent: false });
          }

          if (this.ctx.raId && raControl) {
            raControl.setValue(this.ctx.raId, { emitEvent: false });
            raControl.disable({ emitEvent: false });
          }


          /* re‑apply record for edit / view after look‑ups exist */
          if (prePatch) {
            this.form.patchValue(prePatch, { emitEvent: false });
          }
          if (this.isViewMode) {
            this.form.disable({ emitEvent: false });
          }
        },
        error: err => this.toast.error(err?.error?.message)
      });
  }

  /* ────────── responsible helper ────────── */
  onRespSelected(item: { type: 'PERSON' | 'PERSON_GROUP' }): void {
    if (item) {
      this.form.patchValue(
        { responsible_for_implementation_id_ref_type: item.type },
        { emitEvent: false }
      );
    }
  }

  /* ────────── save (add / update) ────────── */
  onSave(): void {
    if (this.isViewMode) { this.loc.back(); return; }

    if (this.form.invalid) {
      this.toast.error('Please fill all mandatory fields.');
      this.form.markAllAsTouched();
      return;
    }

    const payload = this.form.getRawValue() as ControlMeasureAssignment;

    this.isSaving = true;
    this.loader.show();

    const stop = () => { this.isSaving = false; this.loader.hide(); };

    if (this.isEditMode && this.assignmentId) {
      payload.public_id = this.assignmentId;
      this.srvAssign.updateAssignment(this.assignmentId, payload).subscribe({
        next: () => { stop(); this.toast.success('Updated'); this.loc.back(); },
        error: err => { stop(); this.toast.error(err?.error?.message); }
      });
    } else {
      this.srvAssign.createAssignment(payload).subscribe({
        next: () => { stop(); this.toast.success('Created'); this.loc.back(); },
        error: err => { stop(); this.toast.error(err?.error?.message); }
      });
    }
  }


  onCancel(): void { this.loc.back(); }
}
