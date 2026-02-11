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

import { ConnectorsRoutingModule } from './connectors-routing.module';
import { ConnectorsComponent } from './connectors.component';
import { ConnectorsListComponent } from './components/connectors-list/connectors-list.component';
import { ConnectorFormComponent } from './components/connector-form/connector-form.component';

import { CoreModule } from '../../core/core.module';
import { TableModule } from '../../layout/table/table.module';
import { AuthModule } from 'src/app/modules/auth/auth.module';

@NgModule({
  declarations: [
    ConnectorsComponent,
    ConnectorsListComponent,
    ConnectorFormComponent
  ],
  imports: [
    CommonModule,
    FormsModule,
    ReactiveFormsModule,

    CoreModule,
    TableModule,
    ConnectorsRoutingModule,
    AuthModule
  ]
})
export class ConnectorsModule {}
