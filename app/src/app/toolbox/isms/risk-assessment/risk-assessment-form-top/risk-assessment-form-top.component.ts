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
import { Component, inject, Input, OnInit } from '@angular/core';
import { FormGroup } from '@angular/forms';
import { finalize } from 'rxjs/operators';

import { LoaderService } from 'src/app/core/services/loader.service';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { TypeService } from 'src/app/framework/services/type.service';
import { ObjectService } from 'src/app/framework/services/object.service';
import { RenderResult } from 'src/app/framework/models/cmdb-render';

/* Minimal CMDB typings */
interface CmdbType   { public_id: number; }
interface CmdbObject { public_id: number; type_id: number; name: string; }

@Component({
  selector: 'app-risk-assessment-form-top',
  templateUrl: './risk-assessment-form-top.component.html',
  styleUrls: ['./risk-assessment-form-top.component.scss']
})
export class RiskAssessmentFormTopComponent implements OnInit {

  /* ──────── Inputs ──────── */
  @Input() parentForm!: FormGroup;

  @Input() fromRisk        = false;
  @Input() fromObject      = false;
  @Input() fromObjectGroup = false;
  @Input() fromReport = false;

  @Input() risks:        any[]        = [];
  // @Input() objects:      CmdbObject[] = [];
  @Input() objectGroups: any[]        = [];

  @Input() objectSummary:   string | null = null;
  @Input() riskSummaryLine: string | null = null;
  @Input() mode: 'EDIT' | 'VIEW' = 'EDIT';

  /* ──────── Services ──────── */
  private readonly typeService   = inject(TypeService);
  private readonly loader        = inject(LoaderService);
  private readonly toast         = inject(ToastService);
  private readonly objectService = inject(ObjectService);

  /* ──────── State ──────── */
  public riskName: string | null = null;
  public selectedObjectRenderResult: RenderResult | null = null;
  public isObjectLoading = false;

  public allTypeIds: number[] = [];
  public typesLoaded = false;

  public objectRefTypes = [
    { label: 'Object',       value: 'OBJECT' },
    { label: 'Object Group', value: 'OBJECT_GROUP' }
  ];

  private static cachedTypes: CmdbType[] | null = null;

  /* ══════════════════════════════════════ */


  ngOnInit(): void {
    const objectId = this.parentForm.get('object_id')?.value;
    const riskId = this.parentForm.get('risk_id')?.value;
  
    //  Resolve risk name in all scenarios
    if (riskId) {
      this.riskName =
        this.risks.find(r => r.public_id === riskId)?.name
        ?? this.riskSummaryLine
        ?? null;
    }
  
    //  Enable object selector only if fromRisk and not VIEW
    if (this.fromRisk && this.mode !== 'VIEW') {
      this.loadTypesIfNeeded();
    }
  
    //  Lock both in report mode
    if (this.fromReport) {
      this.parentForm.get('risk_id')?.disable({ emitEvent: false });
      this.parentForm.get('object_id_ref_type')?.disable({ emitEvent: false });
      this.parentForm.get('object_id')?.disable({ emitEvent: false });
    }
  
    //  Lock object ref type in object-based context (edit/view/add)
    if (this.fromObject || this.fromObjectGroup) {
      this.parentForm.get('object_id_ref_type')?.disable({ emitEvent: false });
      this.parentForm.get('object_id')?.disable({ emitEvent: false });
    }
  
    //  Lock risk_id only in VIEW mode for object/group
    if ((this.fromObject || this.fromObjectGroup) && this.mode === 'VIEW') {
      this.parentForm.get('risk_id')?.disable({ emitEvent: false });
    }
  
    //  Lock risk_id if fromRisk (view/edit/add)
    if (this.fromRisk) {
      this.parentForm.get('risk_id')?.disable({ emitEvent: false });
    }
  
    // Load render view if applicable
    const shouldRender =
      (this.fromObject || this.fromReport || (this.fromRisk && this.mode === 'VIEW'));
  
    if (shouldRender && objectId) {
      this.loadSelectedObjectRenderResult(objectId);
    }

  }
  
  

  public onObjectSelected(ids: number[]): void {
    this.parentForm.get('object_id')?.setValue(ids?.[0] ?? null);
  }

  private loadTypesIfNeeded(): void {
    if (RiskAssessmentFormTopComponent.cachedTypes) {
      this.allTypeIds = RiskAssessmentFormTopComponent.cachedTypes.map(t => t.public_id);
      this.typesLoaded = true;
      return;
    }

    this.loader.show();
    const params = { filter: '', limit: 0, sort: 'sort', order: 1, page: 1 };

    this.typeService.getTypes(params)
      .pipe(finalize(() => this.loader.hide()))
      .subscribe({
        next: (resp) => {
          const types = resp.results as CmdbType[];
          RiskAssessmentFormTopComponent.cachedTypes = types;
          this.allTypeIds = types.map(t => t.public_id);
          this.typesLoaded = true;
        },
        error: (err) => {
          this.toast.error(err?.error?.message ?? 'Failed to load types');
        }
      });
  }

  private loadSelectedObjectRenderResult(objectId: number): void {
    if (!objectId) return;

    this.isObjectLoading = true;
    const params = {
      filter: { public_id: objectId },
      limit: 1,
      sort: '',
      order: 1,
      page: 1
    };

    this.objectService.getObjects(params)
      .pipe(finalize(() => (this.isObjectLoading = false)))
      .subscribe({
        next: (resp) => {
          const result = resp?.results?.[0];
          if (result?.object_information) {
            this.selectedObjectRenderResult = result as RenderResult;
          }
        },
        error: (err) => {
          this.toast.error(err?.error?.message ?? 'Failed to load object');
        }
      });
  }
}
