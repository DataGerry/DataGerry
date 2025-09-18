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
import {
  Component, Input, OnInit, DestroyRef
} from '@angular/core';
import { FormBuilder, FormGroup, Validators } from '@angular/forms';
import { NgbActiveModal } from '@ng-bootstrap/ng-bootstrap';
import { map, finalize } from 'rxjs/operators';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';

import { LoaderService }           from 'src/app/core/services/loader.service';
import { ToastService }            from 'src/app/layout/toast/toast.service';

import { APIGetMultiResponse }     from 'src/app/services/models/api-response';
import { ObjectGroupService } from 'src/app/framework/services/object-group.service';
import { ObjectService } from 'src/app/framework/services/object.service';
import { TypeService } from 'src/app/framework/services/type.service';
import { RiskAssessment } from '../../../models/risk-assessment.model';
import { RiskAssessmentService } from '../../../services/risk-assessment.service';
import { RiskService } from '../../../services/risk.service';

interface SelectOption { public_id: number; name: string; }
type Ctx = 'OBJECT' | 'GROUP' | 'RISK';

@Component({
  selector   : 'app-duplicate-risk-assessment-modal',
  templateUrl: './duplicate-risk-assessment.modal.html',
  styleUrls  : ['./duplicate-risk-assessment.modal.scss']
})
export class DuplicateRiskAssessmentModalComponent implements OnInit {

  /* ───── inputs ───── */
  @Input({ required: true }) ctx!: Ctx;
  @Input({ required: true }) item!: RiskAssessment;
  @Input() objectSummaryLine = '';
  @Input() objectGroupName   = '';
  @Input() riskSummaryLine   = '';

  /* ───── form ───── */
  form!: FormGroup;

  /* ───── selector data ───── */
  options: SelectOption[] = [];   // RISKS / GROUPS
  allTypeIds: number[]    = [];   // OBJECT selector
  typesLoaded = false;
  loading     = false;

  constructor(
    public  activeModal         : NgbActiveModal,
    private fb                  : FormBuilder,
    private raService           : RiskAssessmentService,
    private riskService         : RiskService,
    private objectService       : ObjectService,
    private objectGroupService  : ObjectGroupService,
    private typeService         : TypeService,
    private loader              : LoaderService,
    private toast               : ToastService,
    private readonly destroyRef : DestroyRef
  ) {}

  /* ══════════════════ init ══════════════════ */
  ngOnInit(): void {
    this.form = this.fb.group({
      targets: [ [] as number[], Validators.required ],
      copyCma: [ false ]
    });
    this.fetchSelectorData();
  }

  /* ─────────── selector loader ─────────── */
  private fetchSelectorData(): void {
    this.loader.show(); this.loading = true;
    const p = { filter: '', limit: 0, page: 1, sort: 'name', order: 1 };

    if (this.ctx === 'OBJECT' || this.ctx === 'GROUP') {
      this.riskService.getRisks(p).pipe(
        map((r: APIGetMultiResponse<any>) => r.results as SelectOption[]),
        finalize(() => { this.loader.hide(); this.loading = false; }),
        takeUntilDestroyed(this.destroyRef)
      ).subscribe({
        next : opts => this.options = opts,
        error: err  => this.toast.error(err?.error?.message)
      });
      return;
    }

    if (this.item.object_id_ref_type === 'OBJECT_GROUP') {
      this.objectGroupService.getObjectGroups(p).pipe(
        map((r: APIGetMultiResponse<any>) => r.results as SelectOption[]),
        finalize(() => { this.loader.hide(); this.loading = false; }),
        takeUntilDestroyed(this.destroyRef)
      ).subscribe({
        next : opts => this.options = opts,
        error: err  => this.toast.error(err?.error?.message || 'Load failed')
      });
    } else {
      const tp = { filter: '', limit: 0, page: 1, sort: 'sort', order: 1, projection: ['public_id', 'label', 'name'],};
      this.typeService.getTypes(tp).pipe(
        map((r: APIGetMultiResponse<any>) => r.results.map((t: any) => t.public_id)),
        finalize(() => { this.typesLoaded = true; this.loader.hide(); this.loading = false; }),
        takeUntilDestroyed(this.destroyRef)
      ).subscribe({
        next : ids  => this.allTypeIds = ids,
        error: err  => this.toast.error(err?.error?.message || 'Load failed')
      });
    }
  }

  /* ─────────── helpers ─────────── */
  get selectorKind(): 'RISKS' | 'OBJECTS' | 'GROUPS' {
    if (this.ctx === 'OBJECT' || this.ctx === 'GROUP') return 'RISKS';
    return this.item.object_id_ref_type === 'OBJECT' ? 'OBJECTS' : 'GROUPS';
  }

  get selectorLabel(): string {
    return this.selectorKind === 'RISKS'  ? 'Select risks'
         : this.selectorKind === 'OBJECTS'? 'Select objects'
         :                                   'Select object groups';
  }

  get ready(): boolean {
    if (this.selectorKind === 'OBJECTS') return !this.loading && this.typesLoaded;
    return !this.loading && !!this.options.length;
  }

  /* ─────────── build payload (exclude target IDs & PKs) ─────────── */
  private buildPayload(): any {
    // Strip keys BE should generate and targets (handled via URL)
    const {
      public_id, risk_id, object_id, object_id_ref_type, ...rest
    } = this.item as any;
    return { ...rest };
  }

  /* ─────────── submit ─────────── */
  submit(): void {
    if (this.form.invalid) return;

    const targets = this.form.value.targets as number[];
    const copyCma = this.form.value.copyCma;

    const refType: 'risk' | 'object' | 'object_group' =
      this.ctx === 'RISK'
        ? (this.item.object_id_ref_type === 'OBJECT' ? 'object' : 'object_group')
        : 'risk';

    // const payload = this.buildPayload();

    this.loader.show(); this.loading = true;

    this.raService.duplicateRiskAssessments(targets, refType, copyCma, this.item)
      .pipe(
        finalize(() => { this.loader.hide(); this.loading = false; }),
        takeUntilDestroyed(this.destroyRef)
      )
      .subscribe({
        next : () => { this.toast.success('Duplicated'); this.activeModal.close('done'); },
        error: err  => this.toast.error(err?.error?.message || 'Duplicate failed')
      });
  }
}
