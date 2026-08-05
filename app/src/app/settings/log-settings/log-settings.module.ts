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
*
* You should have received a copy of the GNU Affero General Public License
* along with this program. If not, see <https://www.gnu.org/licenses/>.
*/
import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';

import { NgbProgressbarModule, NgbTooltipModule } from '@ng-bootstrap/ng-bootstrap';
import { FontAwesomeModule } from '@fortawesome/angular-fontawesome';

import { LogSettingsRoutingModule } from './log-settings-routing.module';
import { LayoutModule } from '../../layout/layout.module';
import { AuthModule } from '../../modules/auth/auth.module';
import { TableModule } from '../../layout/table/table.module';
import { ObjectModule } from '../../framework/object/object.module';
import { UsersModule } from '../../management/users/users.module';
import { RenderModule } from '../../framework/render/render.module';

import { DeleteModalComponent, LogObjectSettingsComponent } from './log-object-settings/log-object-settings.component';
import { ActivateTabComponent } from './log-object-settings/activate-tab/activate-tab.component';
import { DeactivateTabComponent } from './log-object-settings/deactivate-tab/deactivate-tab.component';
import { DeleteTabComponent } from './log-object-settings/delete-tab/delete-tab.component';
import { LogSettingsComponent } from './log-settings.component';
import { LogObjectTableActionsComponent } from './log-object-settings/log-object-table-actions/log-object-table-actions.component';
import { CoreModule } from 'src/app/core/core.module';
/* ------------------------------------------------------------------------------------------------------------------ */

@NgModule({
    declarations: [
        LogObjectSettingsComponent,
        ActivateTabComponent,
        DeactivateTabComponent,
        DeleteTabComponent,
        LogSettingsComponent,
        LogObjectTableActionsComponent,
        DeleteModalComponent
    ],
    imports: [
        CommonModule,
        LayoutModule,
        LogSettingsRoutingModule,
        NgbTooltipModule,
        NgbProgressbarModule,
        FontAwesomeModule,
        AuthModule,
        TableModule,
        ObjectModule,
        UsersModule,
        RenderModule,
        CoreModule
    ]
})
export class LogSettingsModule { }