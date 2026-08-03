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
import { Routes, RouterModule } from '@angular/router';

import { PermissionGuard } from '../modules/auth/guards/permission.guard';

import { ExportTypesComponent } from './export-types/export-types.component';
import { ExportComponent } from './export.component';
import { ExportObjectsComponent } from './export-objects/export-objects.component';
import { ExportCsvTemplatesComponent } from './export-csv-templates/export-csv-templates.component';
/* ------------------------------------------------------------------------------------------------------------------ */

const routes: Routes = [
    {
        path: '',
        pathMatch: 'full',
        canActivate: [PermissionGuard],
        data: {
            breadcrumb: 'Overview'
        },
        component: ExportComponent
    },
    {
        path: 'objects',
        canActivate: [PermissionGuard],
        data: {
            breadcrumb: 'Objects',
            right: 'base.export.object.*'
        },
        component: ExportObjectsComponent
    },
    {
        path: 'types',
        canActivate: [PermissionGuard],
        data: {
            breadcrumb: 'Types',
            right: 'base.export.type.*'
        },
        component: ExportTypesComponent
    },
    {
        path: 'csv-templates',
        canActivate: [PermissionGuard],
        data: {
            breadcrumb: 'CSV Templates',
            right: 'base.export.object.*'
        },
        component: ExportCsvTemplatesComponent
    }
];

@NgModule({
    imports: [RouterModule.forChild(routes)],
    exports: [RouterModule]
})
export class ExportRoutingModule {}