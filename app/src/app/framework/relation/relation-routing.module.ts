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
import { UserSettingsResolver } from '../../management/user-settings/resolvers/user-settings-resolver.service';
import { RelationDeleteComponent } from './relation-delete/relation-delete.component';
import { RelationAddComponent } from './relation-add/relation-add.component';
import { RelationComponent } from './relation.component';
import { RelationResolver } from '../resolvers/relation-resolver.service';
import { RelationEditComponent } from './relation-edit/relation-edit.component';

const routes: Routes = [
  {
    path: '',
    pathMatch: 'full',
    data: {
      breadcrumb: '',
      right: 'base.framework.relation.view'
    },
    resolve: {
      userSetting: UserSettingsResolver
    },    component: RelationComponent
  },
  {
    path: 'add',
    data: {
      breadcrumb: 'Add',
      right: 'base.framework.relation.add'
    },
    component: RelationAddComponent
  },
  {
    path: 'edit/:publicID',
    data: {
      breadcrumb: 'Edit',
      right: 'base.framework.relation.edit',
    },
    resolve: {
      type: RelationResolver
    },
    component: RelationEditComponent
  }
  ,
  {
    path: 'delete/:publicID',
    data: {
      breadcrumb: 'Delete',
      right: 'base.framework.relation.delete'
    },
    component: RelationDeleteComponent
  }
];

@NgModule({
  imports: [RouterModule.forChild(routes)],
  exports: [RouterModule]
})
export class RelationRoutingModule { }
