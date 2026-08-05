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
import { AutomationWizardComponent } from './wizard/components/automation-wizard/automation-wizard.component';
import { AuthGuard } from 'src/app/modules/auth/guards/auth.guard';
import { ConnectorFormComponent } from './connectors/components/connector-form/connector-form.component';
import { PermissionGuard } from 'src/app/modules/auth/guards/permission.guard';

const routes: Routes = [
  {
    path: '',
    component: AutomationsComponent,
    canActivate: [AuthGuard, PermissionGuard],
    data: {
      right: 'base.openCelium.connection.view'
    },
    children: [
      {
        path: '',
        component: AutomationsListComponent,
        canActivate: [AuthGuard, PermissionGuard],
        data: {
          right: 'base.openCelium.connection.view',
          breadcrumb: 'Automations'
        }
      },
      {
        path: 'add',
        component: AutomationWizardComponent,
        canActivate: [AuthGuard, PermissionGuard],
        data: {
          right: 'base.openCelium.connection.add',
          breadcrumb: 'Create Automation',
          mode: 'create'
        }
      },
      {
        path: 'edit/:schedulerId',
        component: AutomationWizardComponent,
        canActivate: [AuthGuard, PermissionGuard],
        data: {
          right: 'base.openCelium.connection.edit',
          breadcrumb: 'Edit Automation',
          mode: 'edit'
        }
      },
      {
        path: 'internal',
        component: ConnectorFormComponent,
        canActivate: [AuthGuard, PermissionGuard],
        data: {
          right: 'base.openCelium.connector.*',
          mode: 'internal',
          breadcrumb: 'DataGerry API Credentials'
        }
      },
      {
        path: 'connectors/internal',
        component: ConnectorFormComponent,
        canActivate: [AuthGuard, PermissionGuard],
        data: {
          right: 'base.openCelium.connector.*',
          mode: 'internal',
          breadcrumb: 'DataGerry API Credentials'
        }
      }
    ]
  }
];

@NgModule({
  imports: [RouterModule.forChild(routes)],
  exports: [RouterModule]
})
export class AutomationsRoutingModule {}
