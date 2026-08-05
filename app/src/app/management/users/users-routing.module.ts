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

import { GroupsResolver, OwnGroupResolver } from '../resolvers/group-resolver.service';
import { ProviderResolver } from '../../modules/auth/resolvers/provider-resolver.service';
import { OwnUserResolver, UserResolver } from '../resolvers/user-resolver.service';

import { UserViewComponent } from './user-view/user-view.component';
import { UsersComponent } from './users.component';
import { UserAddComponent } from './user-add/user-add.component';
import { UserEditComponent } from './user-edit/user-edit.component';
import { UserDeleteComponent } from './user-delete/user-delete.component';
/* ------------------------------------------------------------------------------------------------------------------ */

const routes: Routes = [
    {
        path: '',
        pathMatch: 'full',
        data: {
            breadcrumb: 'List',
            right: 'base.user-management.user.view'
        },
        component: UsersComponent
    },
    {
        path: 'view',
        data: {
            breadcrumb: 'View',
            right: 'base.user-management.user.view',
        },
        resolve: {
            user: OwnUserResolver,
            group: OwnGroupResolver
        },
        component: UserViewComponent
    },
    {
        path: 'add',
        data: {
            breadcrumb: 'Add',
            right: 'base.user-management.user.add'
        },
        resolve: {
            groups: GroupsResolver,
            providers: ProviderResolver
        },
        component: UserAddComponent
    },
    {
        path: 'edit/:publicID',
        data: {
            breadcrumb: 'Edit',
            right: 'base.user-management.user.edit'
        },
        resolve: {
            user: UserResolver,
            groups: GroupsResolver,
            providers: ProviderResolver
        },
        component: UserEditComponent
    },
    {
        path: 'delete/:publicID',
        data: {
            breadcrumb: 'Delete',
            right: 'base.user-management.user.delete'
        },
        resolve: {
            user: UserResolver
        },
        component: UserDeleteComponent
    }
];

@NgModule({
    imports: [RouterModule.forChild(routes)],
    exports: [RouterModule]
})
export class UsersRoutingModule {}