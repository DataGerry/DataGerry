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
import { CategoryComponent } from './category.component';
import { CategoryAddComponent } from './category-add/category-add.component';
import { CategoryEditComponent } from './category-edit/category-edit.component';
import { CmdbMode } from '../modes.enum';
import { CategoryViewComponent } from './category-view/category-view.component';
import { UserSettingsResolver } from '../../management/user-settings/resolvers/user-settings-resolver.service';

const routes: Routes = [
  {
    path: '',
    pathMatch: 'full',
    data: {
      breadcrumb: 'List',
      right: 'base.framework.category.view',
      mode: CmdbMode.View
    },
    resolve: {
      userSetting: UserSettingsResolver
    },
    component: CategoryComponent
  },
  {
    path: 'view/:publicID',
    data: {
      breadcrumb: 'View',
      right: 'base.framework.category.view',
      mode: CmdbMode.View
    },
    component: CategoryViewComponent
  },
  {
    path: 'add',
    data: {
      breadcrumb: 'Add',
      right: 'base.framework.category.add'
    },
    component: CategoryAddComponent
  },
  {
    path: 'edit',
    data: {
      breadcrumb: 'Edit',
      right: 'base.framework.category.edit',
      mode: CmdbMode.Edit
    },
    component: CategoryComponent
  },
  {
    path: 'edit/:publicID',
    data: {
      breadcrumb: 'Edit',
      right: 'base.framework.category.edit',
      mode: CmdbMode.Edit
    },
    component: CategoryEditComponent
  }
];

@NgModule({
  imports: [RouterModule.forChild(routes)],
  exports: [RouterModule]
})
export class CategoryRoutingModule {
}
