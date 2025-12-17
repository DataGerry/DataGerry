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
*
* You should have received a copy of the GNU Affero General Public License
* along with this program. If not, see <https://www.gnu.org/licenses/>.
*/
import { NgModule } from '@angular/core';
import { Routes, RouterModule } from '@angular/router';

import { PermissionGuard } from '../modules/auth/guards/permission.guard';

import { UserSettingsResolver } from './user-settings/resolvers/user-settings-resolver.service';

import { ManagementComponent } from './management.component';
/* ------------------------------------------------------------------------------------------------------------------ */

const routes: Routes = [
    {
        path: '',
        pathMatch: 'full',
        canActivate: [PermissionGuard],
        data: {
            breadcrumb: 'Overview',
            right: 'base.user-management.*'
        },
        component: ManagementComponent
    },
    {
        path: 'users',
        canActivateChild: [PermissionGuard],
        data: {
            breadcrumb: 'Users',
            right: 'base.user-management.user.view'
        },
        resolve: {
            userSetting: UserSettingsResolver
        },
        loadChildren: () => import('./users/users.module').then(m => m.UsersModule)
    },
    {
        path: 'groups',
        canActivateChild: [PermissionGuard],
        data: {
            breadcrumb: 'Groups',
            right: 'base.user-management.group.view'
        },
        loadChildren: () => import('./groups/groups.module').then(m => m.GroupsModule)
    },
    {
        path: 'rights',
        data: {
            breadcrumb: 'Rights',
        },
        loadChildren: () => import('./rights/rights.module').then(m => m.RightsModule)
    }
];

@NgModule({
    imports: [RouterModule.forChild(routes)],
    exports: [RouterModule]
})
export class ManagementRoutingModule { }