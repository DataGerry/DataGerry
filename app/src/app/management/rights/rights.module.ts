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

import { RightsRoutingModule } from './rights-routing.module';
import { RightLevelColorDirective } from './right-level-color.directive';
import { RightsComponent } from './rights.component';
import { TableModule } from '../../layout/table/table.module';
import { RightLevelCardComponent } from './components/right-level-card/right-level-card.component';
import { RightTableLevelCellComponent } from './components/right-table-level-cell/right-table-level-cell.component';
import { RightTableGroupsCellComponent } from './components/right-table-groups-cell/right-table-groups-cell.component';
import { RightGroupsModalComponent } from './modals/right-groups-modal/right-groups-modal.component';
import { GroupsModule } from '../groups/groups.module';
import { LayoutModule } from 'src/app/layout/layout.module';
import { CoreModule } from 'src/app/core/core.module';

@NgModule({
  imports: [
    CommonModule,
    RightsRoutingModule,
    TableModule,
    GroupsModule,
    CoreModule
  ],
  declarations: [
    RightLevelColorDirective,
    RightsComponent,
    RightLevelCardComponent,
    RightTableLevelCellComponent,
    RightTableGroupsCellComponent,
    RightGroupsModalComponent
  ]
})
export class RightsModule {
}
