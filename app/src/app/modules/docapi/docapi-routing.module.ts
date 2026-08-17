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

import { DocapiListComponent } from './components/docapi-list/docapi-list.component';
import { DocapiAddComponent } from './components/docapi-add/docapi-add.component';
import { DocapiEditComponent } from './components/docapi-edit/docapi-edit.component';
/* ------------------------------------------------------------------------------------------------------------------ */

const routes: Routes = [
  {
        path: '',
        pathMatch: 'full',
        data: {
            breadcrumb: 'List',
            right: 'base.docapi.template.view'
        },
        component: DocapiListComponent
  },
  {
        path: 'add',
        data: {
            breadcrumb: 'Add',
            right: 'base.docapi.template.add'
        },
        component: DocapiAddComponent
  },
  {
        path: 'edit/:publicId',
        data: {
            breadcrumb: 'Edit',
            right: 'base.docapi.template.edit'
        },
        component: DocapiEditComponent
  }
];

@NgModule({
    imports: [RouterModule.forChild(routes)],
    exports: [RouterModule]
})
export class DocapiRoutingModule {}
