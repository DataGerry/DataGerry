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

import { RiskAssessmentAddComponent } from './risk-assessment-add/risk-assessment-add.component';
import { RiskAssessmentListComponent } from './risk-assesment-list/risk-assessment-list.component';

// These routes are registered as siblings of the ISMS shell route, so they are not covered
// by its canActivateChild and each one guards itself.
const routes: Routes = [
  /* ➜ CREATE ------------------------------------------------------------- */
  {
    path: 'risks/:riskId/risk-assessments/add',
    component: RiskAssessmentAddComponent,
    canActivate: [PermissionGuard],
    data: {
      breadcrumb: 'Add Risk Assessment (Risk)',
      right: 'base.isms.riskAssessment.add'
    }
  },
  {
    path: 'objects/:objectId/risk-assessments/add',
    component: RiskAssessmentAddComponent,
    canActivate: [PermissionGuard],
    data: {
      breadcrumb: 'Add Risk Assessment (Object)',
      right: 'base.isms.riskAssessment.add'
    }
  },
  {
    path: 'object-groups/:groupId/risk-assessments/add',
    component: RiskAssessmentAddComponent,
    canActivate: [PermissionGuard],
    data: {
      breadcrumb: 'Add Risk Assessment (Group)',
      right: 'base.isms.riskAssessment.add'
    }
  },

  /* ➜ LIST --------------------------------------------------------------- */
  {
    path: 'risks/:riskId/risk-assessments',
    component: RiskAssessmentListComponent,
    canActivate: [PermissionGuard],
    data: {
      breadcrumb: 'Risk Assessments (Risk)',
      right: 'base.isms.riskAssessment.view'
    }
  },
  {
    path: 'objects/:objectId/risk-assessments',
    component: RiskAssessmentListComponent,
    canActivate: [PermissionGuard],
    data: {
      breadcrumb: 'Risk Assessments (Object)',
      right: 'base.isms.riskAssessment.view'
    }
  },
  {
    path: 'object-groups/:groupId/risk-assessments',
    component: RiskAssessmentListComponent,
    canActivate: [PermissionGuard],
    data: {
      breadcrumb: 'Risk Assessments (Group)',
      right: 'base.isms.riskAssessment.view'
    }
  },

  /* ➜ EDIT --------------------------------------------------------------- */
  {
    path: 'risks/:riskId/risk-assessments/edit/:id',
    component: RiskAssessmentAddComponent,
    canActivate: [PermissionGuard],
    data: {
      breadcrumb: 'Edit Risk Assessment (Risk)',
      right: 'base.isms.riskAssessment.edit'
    }
  },
  {
    path: 'objects/:objectId/risk-assessments/edit/:id',
    component: RiskAssessmentAddComponent,
    canActivate: [PermissionGuard],
    data: {
      breadcrumb: 'Edit Risk Assessment (Object)',
      right: 'base.isms.riskAssessment.edit'
    }
  },
  {
    path: 'object-groups/:groupId/risk-assessments/edit/:id',
    component: RiskAssessmentAddComponent,
    canActivate: [PermissionGuard],
    data: {
      breadcrumb: 'Edit Risk Assessment (Group)',
      right: 'base.isms.riskAssessment.edit'
    }
  },

  /* ➜ VIEW --------------------------------------------------------------- */
  {
    path: 'risks/:riskId/risk-assessments/view/:id',
    component: RiskAssessmentAddComponent,
    canActivate: [PermissionGuard],
    data: {
      breadcrumb: 'View Risk Assessment (Risk)',
      right: 'base.isms.riskAssessment.view'
    }
  },
  {
    path: 'objects/:objectId/risk-assessments/view/:id',
    component: RiskAssessmentAddComponent,
    canActivate: [PermissionGuard],
    data: {
      breadcrumb: 'View Risk Assessment (Object)',
      right: 'base.isms.riskAssessment.view'
    }
  },
  {
    path: 'object-groups/:groupId/risk-assessments/view/:id',
    component: RiskAssessmentAddComponent,
    canActivate: [PermissionGuard],
    data: {
      breadcrumb: 'View Risk Assessment (Group)',
      right: 'base.isms.riskAssessment.view'
    }
  },

  /* ➜ fall‑back (no context) ---------------------------------------------- */
  {
    path: 'risk-assessments/edit/:id',
    component: RiskAssessmentAddComponent,
    canActivate: [PermissionGuard],
    data: {
      breadcrumb: 'Edit Risk Assessment',
      right: 'base.isms.riskAssessment.edit'
    }
  },
  {
    path: 'risk-assessments/view/:id',
    component: RiskAssessmentAddComponent,
    canActivate: [PermissionGuard],
    data: {
      breadcrumb: 'View Risk Assessment',
      right: 'base.isms.riskAssessment.view'
    }
  },
  {
    path: 'risk-assessments/add',
    component: RiskAssessmentAddComponent,
    canActivate: [PermissionGuard],
    data: {
      breadcrumb: 'Add Risk Assessment',
      right: 'base.isms.riskAssessment.add'
    }
  }
];

@NgModule({
  imports: [RouterModule.forChild(routes)],
  exports: [RouterModule]
})
export class RiskAssessmentRoutingModule {}
