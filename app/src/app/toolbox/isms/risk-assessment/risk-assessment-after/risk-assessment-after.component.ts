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
import { Component, Input, OnInit } from '@angular/core';
import { FormArray, FormGroup } from '@angular/forms';
import { RiskClass } from '../../models/risk-class.model';

const FALLBACK_GREY = '#f5f5f5';

@Component({
    selector: 'app-risk-assessment-after',
    templateUrl: './risk-assessment-after.component.html',
    styleUrls: ['./risk-assessment-after.component.scss'],
    standalone: false
})
export class RiskAssessmentAfterComponent implements OnInit {
  @Input() parentForm!: FormGroup;
  @Input() impacts: any[] = [];
  @Input() likelihoods: any[] = [];
  @Input() impactCategories: any[] = [];
  @Input() riskMatrix: any;
  @Input() riskClasses: RiskClass[];
  @Input() isView = false;

  public displayedLikelihoods: any[] = [];
  public calcRiskBgColor: string = FALLBACK_GREY;
  private riskClassMap = new Map<number, RiskClass>();


  ngOnInit(): void {
    this.displayedLikelihoods = [...this.likelihoods];
    if (this.riskClasses) {
      this.riskClassMap = new Map(this.riskClasses.map((rc) => [rc.public_id, rc]));
    }
    this.bindRecalculation();

  }


  get afterGroup(): FormGroup {
    return this.parentForm.get('risk_calculation_after') as FormGroup;
  }

  get impactsArray(): FormArray {
    return this.afterGroup.get('impacts') as FormArray;
  }

  onImpactChanged(categoryIndex: number, newImpactId: number | null) {
    this.impactsArray.at(categoryIndex).get('impact_id')?.setValue(newImpactId);
    this.recalculateRisk();
  }

  onLikelihoodChanged(newLhId: number | null) {
    this.afterGroup.get('likelihood_id')?.setValue(newLhId);
    this.recalculateRisk();
  }
  

  /*
  * Recalculates the risk value based on selected impacts and likelihood.
  * @returns {void}
  */
  private recalculateRisk(): void {
    // Compute selected impact by picking the one with highest calculation_basis
    const selectedImpact = this.impactsArray.controls
      .map((ctrl) => this.impacts.find(i => i.public_id === +ctrl.get('impact_id')!.value))
      .filter(Boolean)
      .sort((a, b) => b.calculation_basis - a.calculation_basis)[0] ?? null;

    // Get selected likelihood object
    const lhId = this.afterGroup.get('likelihood_id')?.value;
    const selectedLikelihood = this.likelihoods.find(l => l.public_id === +lhId) ?? null;
    const lhVal = selectedLikelihood ? selectedLikelihood.calculation_basis : 0;
    const impactBasis = selectedImpact ? selectedImpact.calculation_basis : 0;
    const impactId    = selectedImpact?.public_id         ?? null;
    const riskVal = impactBasis * lhVal;

    this.afterGroup.patchValue({
      likelihood_value: lhVal,
      maximum_impact_id:    impactId,
      maximum_impact_value: impactBasis,
      risk_level_value: riskVal
    });

    // Update background color based on the selected impact and likelihood
    this.calcRiskBgColor = this.getRiskColor(
      selectedImpact?.public_id ?? 0,
      selectedLikelihood?.public_id ?? 0
    );
  }

  /*
  * Binds the recalculation of risk to the form controls.
  * @returns {void}
  */
  private bindRecalculation(): void {
    this.recalculateRisk();
  }

  /*
* Gets the risk color based on the impact and likelihood IDs.
* @returns {string}
*/
  private getRiskColor(impactId: number, likelihoodId: number): string {
    const cell = this.riskMatrix?.result?.risk_matrix.find((c) =>
      c.impact_id === impactId && c.likelihood_id === likelihoodId
    );
    const cls = cell ? this.riskClassMap.get(cell.risk_class_id) : undefined;
    return cls?.color ?? FALLBACK_GREY;
  }
}
