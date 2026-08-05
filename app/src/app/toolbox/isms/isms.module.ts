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
import { CommonModule } from '@angular/common';
import { FormsModule, ReactiveFormsModule } from '@angular/forms';
import { NgSelectModule } from '@ng-select/ng-select';
import { FontAwesomeModule } from '@fortawesome/angular-fontawesome';
import { ArchwizardModule } from '@rg-software/angular-archwizard';
import { CoreModule } from 'src/app/core/core.module';
import { LayoutModule } from 'src/app/layout/layout.module';
import { AuthModule } from 'src/app/modules/auth/auth.module';
import { IsmsRoutingModule } from './isms-routing.module';

import { IsmsComponent } from './isms.component';
import { OverviewComponent } from './overview/overview.component';
import { ConfigureComponent } from './configure/configure.component';

// Step components under configure/steps
import { RiskClassesComponent } from './configure/steps/risk-classes/risk-classes.component';
import { LikelihoodsComponent } from './configure/steps/likelihood/likelihood.component';
import { ImpactComponent } from './configure/steps/impact/impact.component';
import { ImpactCategoriesComponent } from './configure/steps/impact-categories/impact-categories.component';
import { ProtectionGoalsComponent } from './configure/steps/protection-goals/protection-goals.component';
import { RiskCalculationComponent } from './configure/steps/risk-calculation/risk-calculation.component';
import { TableModule } from 'src/app/layout/table/table.module';
import { RiskClassModalComponent } from './configure/steps/risk-classes/modal/add-risk-class-modal.component';
import { LikelihoodModalComponent } from './configure/steps/likelihood/modal/likelihood-modal.component';
import { ImpactModalComponent } from './configure/steps/impact/modal/impact-modal.component';
import { ImpactCategoryModalComponent } from './configure/steps/impact-categories/modal/impact-category-modal.component';
import { ProtectionGoalModalComponent } from './configure/steps/protection-goals/modal/protection-goal-modal.component';
import { ThreatsListComponent } from './threats/threats-list.component';
import { ThreatsAddComponent } from './threats/add/threats-add.component';
import { VulnerabilitiesListComponent } from './vulnerabilities/vulnerabilities-list.component';
import { VulnerabilitiesAddComponent } from './vulnerabilities/add/vulnerabilities-add.component';
import { RiskAddComponent } from './risks/risks-add/risks-add.component';
import { RisksListComponent } from './risks/risks-list/risks-list.component';
import { RiskAssessmentModule } from './risk-assessment/risk-assesment.module';
import { NgbModule } from '@ng-bootstrap/ng-bootstrap';
import { ControlmeasuresListComponent } from './control-measure/control-measure-list/control-measure-list.component';
import { ControlMeasuresAddComponent } from './control-measure/control-measure-add/control-measures-add.component';
import { RisksFooterComponent } from './risks/risks-footer/risks-footer.component';
import { ControlMeasureFooterComponent } from './control-measure/control-measure-footer/control-measure-footer.component';
import { ControlMeasureAssignmentModule } from './control‑measure‑assignment/control-measure-assignment.module';
import { RiskMatrixReportModule } from './risk-matrix-report/risk-matrix-report.module';
import { SoaComponent } from './reporting/soa/soa.component';
import { RiskTreatmentPlanComponent } from './reporting/risk-treatment-plan/risk-treatment-plan.component';
import { RiskAssesmentsComponent } from './reporting/risk-assesments/risk-assesments.component';
import { ReportsOverviewComponent } from './reporting/overview/reports-overview.component';

@NgModule({
  declarations: [
    IsmsComponent,
    OverviewComponent,
    ConfigureComponent,
    RiskClassesComponent,
    LikelihoodsComponent,
    ImpactComponent,
    ImpactCategoriesComponent,
    ProtectionGoalsComponent,
    RiskCalculationComponent,
    RiskClassModalComponent,
    LikelihoodModalComponent,
    ImpactModalComponent,
    ImpactCategoryModalComponent,
    ProtectionGoalModalComponent,
    ThreatsListComponent,
    ThreatsAddComponent,
    VulnerabilitiesListComponent,
    VulnerabilitiesAddComponent,
    RiskAddComponent,
    RisksListComponent,
    RisksFooterComponent,
    ControlmeasuresListComponent,
    ControlMeasuresAddComponent,
    ControlMeasureFooterComponent,
    SoaComponent,
    RiskTreatmentPlanComponent,
    RiskAssesmentsComponent,
    ReportsOverviewComponent

  ],
  imports: [
    CommonModule,
    LayoutModule,
    ArchwizardModule,
    ReactiveFormsModule,
    NgSelectModule,
    FontAwesomeModule,
    AuthModule,
    CoreModule,
    TableModule,
    FormsModule,
    NgbModule,
    IsmsRoutingModule,
    
    RiskAssessmentModule,
    ControlMeasureAssignmentModule,
    RiskMatrixReportModule  ]
})
export class ISMSModule {}
