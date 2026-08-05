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


import { NgModule } from '@angular/core';
import { RouterModule, Routes } from '@angular/router';


import { IsmsComponent } from './isms.component';
import { OverviewComponent } from './overview/overview.component';
import { ConfigureComponent } from './configure/configure.component';

import { ThreatsListComponent } from './threats/threats-list.component';
import { ThreatsAddComponent } from './threats/add/threats-add.component';

import { VulnerabilitiesListComponent } from './vulnerabilities/vulnerabilities-list.component';
import { VulnerabilitiesAddComponent } from './vulnerabilities/add/vulnerabilities-add.component';

import { RisksListComponent } from './risks/risks-list/risks-list.component';
import { RiskAddComponent } from './risks/risks-add/risks-add.component';

import { ControlmeasuresListComponent } from './control-measure/control-measure-list/control-measure-list.component';
import { ControlMeasuresAddComponent } from './control-measure/control-measure-add/control-measures-add.component';

import { ControlMeasureAssignmentListComponent } from './control‑measure‑assignment/control‑measure‑assignment-list/control‑measure‑assignment-list.component';
import { ControlMeasureAssignmentAddComponent } from './control‑measure‑assignment/control‑measure‑assignment-add/control-measure-assignment-add.component';

import { RiskMatrixReportComponent } from './risk-matrix-report/risk-matrix-report.component';
import { SoaComponent } from './reporting/soa/soa.component';
import { RiskTreatmentPlanComponent } from './reporting/risk-treatment-plan/risk-treatment-plan.component';
import { RiskAssesmentsComponent } from './reporting/risk-assesments/risk-assesments.component';
import { ReportsOverviewComponent } from './reporting/overview/reports-overview.component';

const routes: Routes = [
  {
    path: '',
    component: IsmsComponent,
    // data: { breadcrumb: 'ISMS' },
    children: [
      { path: '', component: OverviewComponent, data: { breadcrumb: 'Overview' } },
      { path: 'overview',  redirectTo: '' },
      { path: 'configure', component: ConfigureComponent, data: { breadcrumb: 'Configure ISMS Settings' } },

      /* ─────────── Threats ─────────── */
      {
        path: 'threats',
        children: [
          { path: '', component: ThreatsListComponent, data: { breadcrumb: 'Threats' } },
          { path: 'add', component: ThreatsAddComponent, data: { breadcrumb: 'Add Threat' } },
          { path: 'edit/:id', component: ThreatsAddComponent, data: { breadcrumb: 'Edit Threat' } },
          { path: 'view', component: ThreatsAddComponent, data: { breadcrumb: 'View Threat' } }
        ]
      },

      /* ─────────── Vulnerabilities ─────────── */
      {
        path: 'vulnerabilities',
        children: [
          { path: '', component: VulnerabilitiesListComponent, data: { breadcrumb: 'Vulnerabilities' } },
          { path: 'add', component: VulnerabilitiesAddComponent, data: { breadcrumb: 'Add Vulnerability' } },
          { path: 'edit', component: VulnerabilitiesAddComponent, data: { breadcrumb: 'Edit Vulnerability' } },
          { path: 'view', component: VulnerabilitiesAddComponent, data: { breadcrumb: 'View Vulnerability' } }
        ]
      },

      /* ─────────── Risks ─────────── */
      {
        path: 'risks',
        data: { breadcrumb: 'Risks' },
        children: [
          { path: '', component: RisksListComponent, data: { breadcrumb: 'Risks' } },
          { path: 'add', component: RiskAddComponent, data: { breadcrumb: 'Add Risk' } },
          { path: 'edit', component: RiskAddComponent, data: { breadcrumb: 'Edit Risk' } },
          { path: 'view', component: RiskAddComponent, data: { breadcrumb: 'View Risk' } }
        ]
      },

      /* ─────────── Control Measures ─────────── */
      {
        path: 'control-measures',
        data: { breadcrumb: 'Controls' },
        children: [
          { path: '', component: ControlmeasuresListComponent, data: { breadcrumb: 'Controls' } },
          { path: 'add', component: ControlMeasuresAddComponent, data: { breadcrumb: 'Add Control' } },
          { path: 'edit', component: ControlMeasuresAddComponent, data: { breadcrumb: 'Edit Control' } },
          { path: 'view', component: ControlMeasuresAddComponent, data: { breadcrumb: 'View Control' } }
        ]
      },

      /* ─────────── Control Measure Assignments ─────────── */
      {
        path: 'control-measure-assignments',
        children: [
          { path: 'view', component: ControlMeasureAssignmentAddComponent, data: { breadcrumb: 'View Assign Control' } },
          { path: 'edit', component: ControlMeasureAssignmentAddComponent, data: { breadcrumb: 'Edit Assign Control' } }
        ]
      },
      {
        path: 'risk_assessments/:riskId/control_measure_assignments',
        component: ControlMeasureAssignmentListComponent,
        data: { breadcrumb: 'Assignments for Risk' }
      },
      {
        path: 'risk_assessments/:riskId/control_measure_assignments/add',
        component: ControlMeasureAssignmentAddComponent,
        data: { breadcrumb: 'Add Assignment to Risk' }
      },
      {
        path: 'control_measures/:cmId/control_measure_assignments',
        component: ControlMeasureAssignmentListComponent,
        data: { breadcrumb: 'Assignments for Control' }
      },
      {
        path: 'control_measures/:cmId/control_measure_assignments/add',
        component: ControlMeasureAssignmentAddComponent,
        data: { breadcrumb: 'Add Assign Control' }
      },

      /* ─────────── Reports ─────────── */
      {
        path: 'reports',
        data: { breadcrumb: 'Reports' },
        children: [
          { path: '', component: ReportsOverviewComponent, data: { breadcrumb: null } }, // <- prevents duplicate "Reports / Reports"
          { path: 'risk_matrix', component: RiskMatrixReportComponent, data: { breadcrumb: 'Risk Matrix Report' } },
          { path: 'soa', component: SoaComponent, data: { breadcrumb: 'Statement of Applicability' } },
          { path: 'risk_treatment_plan', component: RiskTreatmentPlanComponent, data: { breadcrumb: 'Risk Treatment Plan' } },
          { path: 'risk_assesments', component: RiskAssesmentsComponent, data: { breadcrumb: 'Risk Assessments' } }
        ]
      }
      
    ]
  }
];

@NgModule({
  imports: [RouterModule.forChild(routes)],
  exports: [RouterModule]
})
export class IsmsRoutingModule { }
