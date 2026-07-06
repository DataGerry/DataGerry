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
* along with this program.  If not, see <https://www.gnu.org/licenses/>.
*/

import { NgModule } from '@angular/core';
import { Routes, RouterModule } from '@angular/router';
import { ObjectViewComponent } from './object-view/object-view.component';
import { ObjectAddComponent } from './object-add/object-add.component';
import { ObjectEditComponent } from './object-edit/object-edit.component';
import { ObjectCopyComponent } from './object-copy/object-copy.component';
import { ObjectLogComponent } from './object-log/object-log.component';
import { ObjectBulkChangeComponent } from './object-bulk-change/object-bulk-change.component';
import { TypeResolver } from '../resolvers/type-resolver.service';
import { ObjectsByTypeComponent } from './objects-by-type/objects-by-type.component';
import { ObjectViewResolver } from '../resolvers/object-view-resolver.service';
import { UserSettingsResolver } from '../../management/user-settings/resolvers/user-settings-resolver.service';
import { ObjectComponent } from './object.component';
import { ipamObjectGuard } from './guards/ipam-object.guard';


const routes: Routes = [
  {
    path: '',
    pathMatch: 'full',
    data: {
      breadcrumb: 'Object List',
      right: 'base.framework.object.view'
    },
    component: ObjectComponent
  },
  {
    path: 'add',
    data: {
      breadcrumb: 'New',
      right: 'base.framework.object.add'
    },
    component: ObjectAddComponent
  },
  {
    path: 'add/:publicID',
    data: {
      breadcrumb: 'Add',
      right: 'base.framework.object.add'
    },
    component: ObjectAddComponent
  },
  {
    path: 'edit/:publicID',
    data: {
      breadcrumb: 'Edit',
      right: 'base.framework.object.edit'
    },
    canActivate: [ipamObjectGuard],
    component: ObjectEditComponent
  },
  {
    path: 'copy/:publicID',
    data: {
      breadcrumb: 'Copy',
      right: 'base.framework.object.add'
    },
    canActivate: [ipamObjectGuard],
    component: ObjectCopyComponent
  },
  {
    path: 'change',
    data: {
      breadcrumb: 'Bulk change',
      right: 'base.framework.object.*'
    },
    component: ObjectBulkChangeComponent
  },
  {
    path: 'type/:typeID',
    data: {
      breadcrumb: 'Object Type List',
      right: 'base.framework.object.view'
    },
    resolve: {
      type: TypeResolver,
      userSetting: UserSettingsResolver
    },
    component: ObjectsByTypeComponent,
  },
  {
    path: 'view/:publicID',
    data: {
      breadcrumb: 'View',
      right: 'base.framework.object.view'
    },
    canActivate: [ipamObjectGuard],
    resolve: {
      userSetting: UserSettingsResolver,
      object: ObjectViewResolver,
    },
    component: ObjectViewComponent
  },
  {
    path: 'log/:publicID',
    data: {
      breadcrumb: 'View Log',
      right: 'base.framework.object.view'
    },
    component: ObjectLogComponent
  }
];

@NgModule({
  imports: [RouterModule.forChild(routes)],
  exports: [RouterModule]
})
export class ObjectRoutingModule { }
