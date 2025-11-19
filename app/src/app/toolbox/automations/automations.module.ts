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
import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ReactiveFormsModule, FormsModule } from '@angular/forms';
import { RouterModule } from '@angular/router';

import { AutomationsRoutingModule } from './automations-routing.module';
import { AutomationsComponent } from './automations.component';
import { AutomationsListComponent } from './components/automations-list/automations-list.component';
import { AutomationFormComponent } from './components/automation-form/automation-form.component';
import { InternalConnectorPasswordModalComponent } from './components/internal-connector-password-modal/internal-connector-password-modal.component';
import { AutomationsWrapperComponent } from './components/automations-wrapper/automations-wrapper.component';

import { CoreModule } from '../../core/core.module';
import { TableModule } from '../../layout/table/table.module';
import { AuthModule } from 'src/app/modules/auth/auth.module';
import { OpenCeliumEditorComponent } from './components/opencelium-editor.component';

@NgModule({
  declarations: [
    AutomationsWrapperComponent,
    AutomationsComponent,
    AutomationsListComponent,
    AutomationFormComponent,
    InternalConnectorPasswordModalComponent,
    OpenCeliumEditorComponent
  ],
  imports: [
    CommonModule,
    FormsModule,
    ReactiveFormsModule,

    CoreModule,
    TableModule,
    AutomationsRoutingModule,
    AuthModule
  ]
})
export class AutomationsModule {}
