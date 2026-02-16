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
import { Routes, RouterModule } from '@angular/router';

import { AutomationsComponent } from './automations.component';
import { AutomationsListComponent } from './components/automations-list/automations-list.component';
import { AutomationFormComponent } from './components/automation-form/automation-form.component';
import { AuthGuard } from 'src/app/modules/auth/guards/auth.guard';
import { ConnectorFormComponent } from './connectors/components/connector-form/connector-form.component';

const routes: Routes = [
  {
    path: '',
    component: AutomationsComponent,
    canActivate: [AuthGuard],
    data: {
      right: 'automation.view'
    },
    children: [
      {
        path: '',
        component: AutomationsListComponent,
        canActivate: [AuthGuard],
        data: {
          right: 'automation.view',
          breadcrumb: 'Automations'
        }
      },
      {
        path: 'add',
        component: AutomationFormComponent,
        canActivate: [AuthGuard],
        data: {
          right: 'automation.create',
          breadcrumb: 'Create Automation',
          mode: 'create'
        }
      },
      {
        path: 'edit/:schedulerId',
        component: AutomationFormComponent,
        canActivate: [AuthGuard],
        data: {
          right: 'automation.edit',
          breadcrumb: 'Edit Automation',
          mode: 'edit'
        }
      },
      {
        path: 'internal',
        component: ConnectorFormComponent,
        data: { mode: 'internal', breadcrumb: 'DataGerry API Credentials' }
      },
      {
        path: 'connectors/internal',
        component: ConnectorFormComponent,
        data: { mode: 'internal', breadcrumb: 'DataGerry API Credentials' }
      }
    ]
  }
];

@NgModule({
  imports: [RouterModule.forChild(routes)],
  exports: [RouterModule]
})
export class AutomationsRoutingModule {}
