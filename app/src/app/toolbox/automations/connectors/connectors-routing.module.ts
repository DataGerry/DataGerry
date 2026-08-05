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
import { ConnectorsComponent } from './connectors.component';

import { ConnectorsResolver } from './services/connectors-resolver.service';
import { ConnectorFormComponent } from './components/connector-form/connector-form.component';
import { ConnectorsListComponent } from './components/connectors-list/connectors-list.component';
import { PermissionGuard } from 'src/app/modules/auth/guards/permission.guard';

const routes: Routes = [
  {
    path: '',
    component: ConnectorsComponent,
    canActivate: [PermissionGuard],
    canActivateChild: [PermissionGuard],
    data: {
      right: 'base.openCelium.connector.view'
    },
    children: [
      { 
        path: '', 
        component: ConnectorsListComponent,
        data: { breadcrumb: 'Connectors', right: 'base.openCelium.connector.view' }
      },
      {
        path: 'add',
        component: ConnectorFormComponent,
        resolve: { invokers: ConnectorsResolver },
        data: { mode: 'create', breadcrumb: 'Create Connector', right: 'base.openCelium.connector.add' }
      },
      {
        path: 'edit/:id',
        component: ConnectorFormComponent,
        resolve: { invokers: ConnectorsResolver },
        data: { mode: 'edit', breadcrumb: 'Edit Connector', right: 'base.openCelium.connector.edit' }
      }
    ]
  }
];

@NgModule({
  imports: [RouterModule.forChild(routes)],
  exports: [RouterModule]
})
export class ConnectorsRoutingModule {}
