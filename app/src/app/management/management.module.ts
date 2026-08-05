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
* along with this program.  If not, see <https://www.gnu.org/licenses/>.
*/
import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ReactiveFormsModule } from '@angular/forms';

import { ManagementRoutingModule } from './management-routing.module';
import { LayoutModule } from '../layout/layout.module';
import { AuthModule } from '../modules/auth/auth.module';
import { UserSettingsModule } from './user-settings/user-settings.module';

import { UserService } from './services/user.service';
import { GroupService } from './services/group.service';

import { ManagementComponent } from './management.component';
/* ------------------------------------------------------------------------------------------------------------------ */

@NgModule({
    declarations: [
        ManagementComponent
    ],
    imports: [
        CommonModule,
        ManagementRoutingModule,
        LayoutModule,
        ReactiveFormsModule,
        AuthModule,
        UserSettingsModule
    ],
    providers: [
        UserService,
        GroupService
    ],
})
export class ManagementModule {}