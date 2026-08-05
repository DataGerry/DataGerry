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
import { ReactiveFormsModule, FormsModule } from '@angular/forms';
import { RouterModule } from '@angular/router';

import { AutomationsRoutingModule } from './automations-routing.module';
import { AutomationsComponent } from './automations.component';
import { AutomationsListComponent } from './components/automations-list/automations-list.component';
import { AutomationWizardComponent } from './wizard/components/automation-wizard/automation-wizard.component';
import { WizardStepTriggerComponent } from './wizard/components/steps/wizard-step-trigger/wizard-step-trigger.component';
import { WizardStepDataComponent } from './wizard/components/steps/wizard-step-data/wizard-step-data.component';
import { WizardStepTargetComponent } from './wizard/components/steps/wizard-step-target/wizard-step-target.component';
import { WizardStepMappingComponent } from './wizard/components/steps/wizard-step-mapping/wizard-step-mapping.component';
import { WizardStepReviewComponent } from './wizard/components/steps/wizard-step-review/wizard-step-review.component';
import { AutomationSummaryPanelComponent } from './wizard/components/automation-summary-panel/automation-summary-panel.component';
import { AutomationJsonPreviewComponent } from './wizard/components/automation-json-preview/automation-json-preview.component';
import { InternalConnectorPasswordModalComponent } from './components/internal-connector-password-modal/internal-connector-password-modal.component';
import { AutomationsWrapperComponent } from './components/automations-wrapper/automations-wrapper.component';
import { CronExpressionModalComponent } from './components/cron-expression-modal/cron-expression-modal.component';

import { CoreModule } from '../../core/core.module';
import { TableModule } from '../../layout/table/table.module';
import { AuthModule } from 'src/app/modules/auth/auth.module';
import { OpenCeliumLogsViewComponent } from './components/opencelium-log-viewer.component';
import { AutomationLogsMenuComponent } from './components/automation-logs-menu/automation-logs-menu.component';
import { OpenCeliumLogsModalComponent } from './components/opencelium-logs-modal/opencelium-logs-modal.component';
import { AutomationProgressListComponent } from './components/automation-progress-list/automation-progress-list.component';

@NgModule({
  declarations: [
    AutomationsWrapperComponent,
    AutomationsComponent,
    AutomationsListComponent,
    AutomationWizardComponent,
    WizardStepTriggerComponent,
    WizardStepDataComponent,
    WizardStepTargetComponent,
    WizardStepMappingComponent,
    WizardStepReviewComponent,
    AutomationSummaryPanelComponent,
    AutomationJsonPreviewComponent,
    InternalConnectorPasswordModalComponent,
    CronExpressionModalComponent,
    AutomationLogsMenuComponent,
    OpenCeliumLogsModalComponent,
    AutomationProgressListComponent
  ],
  imports: [
    CommonModule,
    FormsModule,
    ReactiveFormsModule,

    CoreModule,
    TableModule,
    AutomationsRoutingModule,
    AuthModule,
    OpenCeliumLogsViewComponent
  ]
})
export class AutomationsModule {}
