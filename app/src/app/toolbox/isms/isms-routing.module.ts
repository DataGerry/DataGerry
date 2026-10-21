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

import { PermissionGuard } from 'src/app/modules/auth/guards/permission.guard';

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
    canActivateChild: [PermissionGuard],
    children: [
      // The overview only reads the ISMS configuration status, which needs no right on the backend.
      { path: '', component: OverviewComponent, data: { breadcrumb: 'Overview' } },
      { path: 'overview',  redirectTo: '' },
      // The wizard spans six right families and each step gates itself, so a single route right
      // would lock out anyone holding only some of them.
      { path: 'configure', component: ConfigureComponent, data: { breadcrumb: 'Configure ISMS Settings' } },

      /* ─────────── Threats ─────────── */
      {
        path: 'threats',
        children: [
          {
            path: '',
            component: ThreatsListComponent,
            data: { breadcrumb: 'Threats', right: 'base.isms.threat.view' }
          },
          {
            path: 'add',
            component: ThreatsAddComponent,
            data: { breadcrumb: 'Add Threat', right: 'base.isms.threat.add' }
          },
          {
            path: 'edit/:id',
            component: ThreatsAddComponent,
            data: { breadcrumb: 'Edit Threat', right: 'base.isms.threat.edit' }
          },
          {
            path: 'view',
            component: ThreatsAddComponent,
            data: { breadcrumb: 'View Threat', right: 'base.isms.threat.view' }
          }
        ]
      },

      /* ─────────── Vulnerabilities ─────────── */
      {
        path: 'vulnerabilities',
        children: [
          {
            path: '',
            component: VulnerabilitiesListComponent,
            data: { breadcrumb: 'Vulnerabilities', right: 'base.isms.vulnerability.view' }
          },
          {
            path: 'add',
            component: VulnerabilitiesAddComponent,
            data: { breadcrumb: 'Add Vulnerability', right: 'base.isms.vulnerability.add' }
          },
          {
            path: 'edit',
            component: VulnerabilitiesAddComponent,
            data: { breadcrumb: 'Edit Vulnerability', right: 'base.isms.vulnerability.edit' }
          },
          {
            path: 'view',
            component: VulnerabilitiesAddComponent,
            data: { breadcrumb: 'View Vulnerability', right: 'base.isms.vulnerability.view' }
          }
        ]
      },

      /* ─────────── Risks ─────────── */
      {
        path: 'risks',
        data: { breadcrumb: 'Risks' },
        children: [
          {
            path: '',
            component: RisksListComponent,
            data: { breadcrumb: 'Risks', right: 'base.isms.risk.view' }
          },
          {
            path: 'add',
            component: RiskAddComponent,
            data: { breadcrumb: 'Add Risk', right: 'base.isms.risk.add' }
          },
          {
            path: 'edit',
            component: RiskAddComponent,
            data: { breadcrumb: 'Edit Risk', right: 'base.isms.risk.edit' }
          },
          {
            path: 'view',
            component: RiskAddComponent,
            data: { breadcrumb: 'View Risk', right: 'base.isms.risk.view' }
          }
        ]
      },

      /* ─────────── Control Measures ─────────── */
      {
        path: 'control-measures',
        data: { breadcrumb: 'Controls' },
        children: [
          {
            path: '',
            component: ControlmeasuresListComponent,
            data: { breadcrumb: 'Controls', right: 'base.isms.controlMeasure.view' }
          },
          {
            path: 'add',
            component: ControlMeasuresAddComponent,
            data: { breadcrumb: 'Add Control', right: 'base.isms.controlMeasure.add' }
          },
          {
            path: 'edit',
            component: ControlMeasuresAddComponent,
            data: { breadcrumb: 'Edit Control', right: 'base.isms.controlMeasure.edit' }
          },
          {
            path: 'view',
            component: ControlMeasuresAddComponent,
            data: { breadcrumb: 'View Control', right: 'base.isms.controlMeasure.view' }
          }
        ]
      },

      /* ─────────── Control Measure Assignments ─────────── */
      {
        path: 'control-measure-assignments',
        children: [
          {
            path: 'view',
            component: ControlMeasureAssignmentAddComponent,
            data: { breadcrumb: 'View Assign Control', right: 'base.isms.controlMeasureAssignment.view' }
          },
          {
            path: 'edit',
            component: ControlMeasureAssignmentAddComponent,
            data: { breadcrumb: 'Edit Assign Control', right: 'base.isms.controlMeasureAssignment.edit' }
          }
        ]
      },
      {
        path: 'risk_assessments/:riskId/control_measure_assignments',
        component: ControlMeasureAssignmentListComponent,
        data: {
          breadcrumb: 'Assignments for Risk',
          right: 'base.isms.controlMeasureAssignment.view'
        }
      },
      {
        path: 'risk_assessments/:riskId/control_measure_assignments/add',
        component: ControlMeasureAssignmentAddComponent,
        data: {
          breadcrumb: 'Add Assignment to Risk',
          right: 'base.isms.controlMeasureAssignment.add'
        }
      },
      {
        path: 'control_measures/:cmId/control_measure_assignments',
        component: ControlMeasureAssignmentListComponent,
        data: {
          breadcrumb: 'Assignments for Control',
          right: 'base.isms.controlMeasureAssignment.view'
        }
      },
      {
        path: 'control_measures/:cmId/control_measure_assignments/add',
        component: ControlMeasureAssignmentAddComponent,
        data: {
          breadcrumb: 'Add Assign Control',
          right: 'base.isms.controlMeasureAssignment.add'
        }
      },

      /* ─────────── Reports ─────────── */
      {
        path: 'reports',
        data: { breadcrumb: 'Reports' },
        children: [
          // <- breadcrumb null prevents duplicate "Reports / Reports"
          {
            path: '',
            component: ReportsOverviewComponent,
            data: { breadcrumb: null, right: 'base.isms.report.view' }
          },
          {
            path: 'risk_matrix',
            component: RiskMatrixReportComponent,
            data: { breadcrumb: 'Risk Matrix Report', right: 'base.isms.report.view' }
          },
          {
            path: 'soa',
            component: SoaComponent,
            data: { breadcrumb: 'Statement of Applicability', right: 'base.isms.report.view' }
          },
          {
            path: 'risk_treatment_plan',
            component: RiskTreatmentPlanComponent,
            data: { breadcrumb: 'Risk Treatment Plan', right: 'base.isms.report.view' }
          },
          {
            path: 'risk_assesments',
            component: RiskAssesmentsComponent,
            data: { breadcrumb: 'Risk Assessments', right: 'base.isms.report.view' }
          }
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
