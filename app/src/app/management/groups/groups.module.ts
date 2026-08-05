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
import { ReactiveFormsModule } from '@angular/forms';
import { GroupsRoutingModule } from './groups-routing.module';

import { NgSelectModule } from '@ng-select/ng-select';
import { FontAwesomeModule } from '@fortawesome/angular-fontawesome';
import { NgbTooltipModule } from '@ng-bootstrap/ng-bootstrap';

import { LayoutModule } from '../../layout/layout.module';
import { AuthModule } from '../../modules/auth/auth.module';
import { TableModule } from '../../layout/table/table.module';
import { UsersModule } from '../users/users.module';
import { AclModule } from 'src/app/modules/acl/acl.module';

import { GroupSelectPipe } from './pipes/group-select.pipe';

import { GroupsComponent } from './groups.component';
import { GroupFormComponent } from './components/group-form/group-form.component';
import { GroupAddComponent } from './group-add/group-add.component';
import { GroupEditComponent } from './group-edit/group-edit.component';
import { GroupDeleteComponent } from './group-delete/group-delete.component';
import { GroupTableUserCellComponent } from './components/group-table-user-cell/group-table-user-cell.component';
import { GroupTableActionsComponent } from './components/group-table-actions/group-table-actions.component';
import { GroupUsersModalComponent } from './modals/group-users-modal/group-users-modal.component';
import { GroupTableListComponent } from './components/group-table-list/group-table-list.component';
import { GroupFormHelperComponent } from './components/group-form/group-form-helper/group-form-helper/group-form-helper.component';
import { GroupAclComponent } from './group-acl/group-acl.component';
import { CoreModule } from 'src/app/core/core.module';
/* ------------------------------------------------------------------------------------------------------------------ */

@NgModule({
    declarations: [
        GroupsComponent,
        GroupFormComponent,
        GroupAddComponent,
        GroupEditComponent,
        GroupDeleteComponent,
        GroupSelectPipe,
        GroupTableUserCellComponent,
        GroupTableActionsComponent,
        GroupUsersModalComponent,
        GroupTableListComponent,
        GroupAclComponent,
        GroupFormHelperComponent
    ],
    exports: [
        GroupTableListComponent
    ],
    imports: [
        CommonModule,
        GroupsRoutingModule,
        ReactiveFormsModule,
        NgSelectModule,
        LayoutModule,
        FontAwesomeModule,
        AuthModule,
        TableModule,
        UsersModule,
        AclModule,
        NgbTooltipModule,
        CoreModule
    ]
})
export class GroupsModule {}