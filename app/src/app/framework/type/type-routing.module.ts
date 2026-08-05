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
import { TypeAddComponent } from './type-add/type-add.component';
import { TypeEditComponent } from './type-edit/type-edit.component';
import { TypeDeleteComponent } from './type-delete/type-delete.component';
import { TypeComponent } from './type.component';
import { TypeResolver } from '../resolvers/type-resolver.service';
import { UserSettingsResolver } from '../../management/user-settings/resolvers/user-settings-resolver.service';

const routes: Routes = [
  {
    path: '',
    pathMatch: 'full',
    data: {
      breadcrumb: '',
      right: 'base.framework.type.view'
    },
    resolve: {
      userSetting: UserSettingsResolver
    },
    component: TypeComponent
  },
  {
    path: 'add',
    data: {
      breadcrumb: 'Add',
      right: 'base.framework.type.add'
    },
    component: TypeAddComponent
  },
  {
    path: 'edit/:typeID',
    data: {
      breadcrumb: 'Edit',
      right: 'base.framework.type.edit',
    },
    resolve: {
      type: TypeResolver
    },
    component: TypeEditComponent
  },
  {
    path: 'delete/:publicID',
    data: {
      breadcrumb: 'Delete',
      right: 'base.framework.type.delete'
    },
    component: TypeDeleteComponent
  }
];

@NgModule({
  imports: [RouterModule.forChild(routes)],
  exports: [RouterModule]
})
export class TypeRoutingModule { }
