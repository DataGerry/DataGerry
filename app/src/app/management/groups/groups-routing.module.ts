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
import { Routes, RouterModule } from '@angular/router';

import { PermissionGuard } from '../../modules/auth/guards/permission.guard';
import { GroupResolver, GroupsResolver } from '../resolvers/group-resolver.service';
import { RightsResolver } from '../resolvers/rights-resolver.service';
import { UserSettingsResolver } from '../user-settings/resolvers/user-settings-resolver.service';

import { GroupsComponent } from './groups.component';
import { GroupAddComponent } from './group-add/group-add.component';
import { GroupEditComponent } from './group-edit/group-edit.component';
import { GroupDeleteComponent } from './group-delete/group-delete.component';
import { GroupAclComponent } from './group-acl/group-acl.component';
/* ------------------------------------------------------------------------------------------------------------------ */

const routes: Routes = [
    {
        path: '',
        pathMatch: 'full',
        data: {
            breadcrumb: 'List',
            right: 'base.user-management.group.view'
        },
        resolve: {
            userSetting: UserSettingsResolver
        },
        component: GroupsComponent
    },
    {
        path: 'add',
        data: {
            breadcrumb: 'Add',
            right: 'base.user-management.group.add'
        },
        resolve: {
            rights: RightsResolver
        },
        component: GroupAddComponent
    },
    {
        path: 'edit/:publicID',
        data: {
            breadcrumb: 'Edit',
            right: 'base.user-management.group.edit'
        },
        resolve: {
            group: GroupResolver,
            rights: RightsResolver
        },
        component: GroupEditComponent
    },
    {
        path: 'delete/:publicID',
        data: {
            breadcrumb: 'Delete',
            right: 'base.user-management.group.delete'
        },
        resolve: {
            group: GroupResolver,
            groups: GroupsResolver
        },
        component: GroupDeleteComponent
    },
    {
        path: 'acl',
        canActivateChild: [PermissionGuard],
        data: {
            breadcrumb: 'Access Control List',
            right: 'base.framework.type.view'
        },
        component: GroupAclComponent
    }
];

@NgModule({
    imports: [RouterModule.forChild(routes)],
    exports: [RouterModule]
})
export class GroupsRoutingModule {}