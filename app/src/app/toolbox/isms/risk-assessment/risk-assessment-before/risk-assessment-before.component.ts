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
  Component,
  DestroyRef,
  Input,
  OnChanges,
  OnInit,
  SimpleChanges,
} from '@angular/core';
import { FormArray, FormGroup } from '@angular/forms';
import {
  combineLatest,
  startWith,
} from 'rxjs';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';

import { RiskClass } from '../../models/risk-class.model';
import { Impact } from '../../models/impact.model';
import { Likelihood } from '../../models/likelihood.model';
import { RiskMatrixCell } from '../../models/risk-matrix.model';
import { getTextColorBasedOnBackground } from 'src/app/core/utils/color-utils';

const FALLBACK_GREY = '#f5f5f5';

@Component({
    selector: 'app-risk-assessment-before',
    templateUrl: './risk-assessment-before.component.html',
    styleUrls: ['./risk-assessment-before.component.scss'],
    standalone: false
})
export class RiskAssessmentBeforeComponent implements OnInit, OnChanges {
  @Input({ required: true }) parentForm!: FormGroup;
  @Input() isView = false;

  @Input() impacts: Impact[] = [];
  @Input() likelihoods: Likelihood[] = [];
  @Input() impactCategories: { name: string }[] = [];

  @Input() allPersons: any[] = [];
  @Input() allPersonGroups: any[] = [];

  @Input() riskMatrix: any;
  @Input() riskClasses: RiskClass[] = [];

  /** single header rows (including "Not rated") */
  impactScaleLabels: string[] = [];
  likelihoodScaleLabels: string[] = [];

  /** computed live */
  calcRiskBgColor = FALLBACK_GREY;

  private riskClassMap = new Map<number, RiskClass>();
  ownerOptions: any[] = [];


  constructor(
    private readonly destroyRef: DestroyRef
  ) { }



  ngOnInit(): void {
    // Include "Not rated" in the labels
    this.impactScaleLabels = ['Not rated', ...this.impacts.map((i) => i.name)];
    this.likelihoodScaleLabels = ['Not rated', ...this.likelihoods.map((l) => l.name)];

    // Build the map if riskClasses input is provided
    if (this.riskClasses && this.riskClasses.length) {
      this.riskClassMap = new Map(this.riskClasses.map((rc) => [rc.public_id, rc]));
    }


    this.bindRecalculation();
  }



  /*
  * Returns the FormGroup of the beforeGroup.
  * @returns {FormGroup}
  */
  get beforeGroup(): FormGroup {
    return this.parentForm.get('risk_calculation_before') as FormGroup;
  }

  /*
  * Returns the FormArray of impacts from the beforeGroup.
  * @returns {FormArray} The FormArray of impacts.
  */
  get impactsArray(): FormArray {
    return this.beforeGroup.get('impacts') as FormArray;
  }


  /*
  * Binds the recalculation of risk to the form value changes.
  * @returns {void}
  */
  private bindRecalculation(): void {
    combineLatest([
      this.impactsArray.valueChanges.pipe(startWith(this.impactsArray.value)),
      this.beforeGroup
        .get('likelihood_id')!
        .valueChanges.pipe(startWith(this.beforeGroup.get('likelihood_id')!.value)),
    ])
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe(() => this.recalculateRisk());
  }


  /*
    * Recalculates the risk based on the selected impacts and likelihood.
    * 1️ - highest impact basis across all categories
    * 2️ - chosen likelihood
    * Updates the form values and background color accordingly.
    * @returns {void}
    */
  private recalculateRisk(): void {
    if (!this.riskMatrix) {
      return;
    }

    // 1 - highest impact basis across all categories
    const selectedImpact = this.impactsArray.controls
      .map((ctrl) =>
        this.impacts.find((i) => i.public_id === +ctrl.get('impact_id')!.value)
      )
      .filter(Boolean)
      .sort((a, b) => (b!.calculation_basis - a!.calculation_basis))[0] ?? null;

    // 2 - chosen likelihood
    const lhId = this.beforeGroup.get('likelihood_id')!.value;
    const selectedLikelihood =
      this.likelihoods.find((l) => l.public_id === +lhId) ?? null;

    const impactBasis = selectedImpact?.calculation_basis ?? 0;
    const impactId = selectedImpact?.public_id ?? null;
    const likelihoodBasis = selectedLikelihood?.calculation_basis ?? 0;
    const risk = impactBasis * likelihoodBasis;

    this.beforeGroup.patchValue(
      {
        maximum_impact_id: impactId,
        likelihood_value: likelihoodBasis,
        maximum_impact_value: impactBasis,
        risk_level_value: risk,
      },
      { emitEvent: false }
    );

    this.calcRiskBgColor = this.getRiskColor(
      selectedImpact?.public_id ?? 0,
      selectedLikelihood?.public_id ?? 0
    );
  }

  private getRiskColor(impactId: number, likelihoodId: number): string {
    const cell: RiskMatrixCell | undefined =
      this.riskMatrix?.result?.risk_matrix.find(
        (c) => c.impact_id === impactId && c.likelihood_id === likelihoodId
      );

    const cls = cell ? this.riskClassMap.get(cell.risk_class_id) : undefined;
    return cls?.color ?? FALLBACK_GREY;
  }

  // Template helper
  trackByIndex = (_: number, i: any) => i;


  ngOnChanges(ch: SimpleChanges): void {
    if (ch['allPersons'] || ch['allPersonGroups']) {
      this.ownerOptions = [
        ...this.allPersonGroups.map(pg => ({
          public_id: pg.public_id,
          display_name: pg.name,
          group: 'Person groups',
          type: 'PERSON_GROUP'
        })),
        ...this.allPersons.map(p => ({
          public_id: p.public_id,
          display_name: p.display_name,
          group: 'Persons',
          type: 'PERSON'
        }))
      ];
    }
  }

  onOwnerSelected(item: any): void {
    if (!item) return;

    this.parentForm.patchValue({
      risk_owner_id_ref_type: item.type   // PERSON / PERSON_GROUP
      // risk_owner_id is **already set** by the CVA above
    }, { emitEvent: false });

  }


  public getTextColor(color: string): string {
    return getTextColorBasedOnBackground(color);
  }
}