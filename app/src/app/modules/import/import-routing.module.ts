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

import { PermissionGuard } from '../auth/guards/permission.guard';

import { ImportComponent } from './import.component';
import { ImportObjectsComponent } from './components/objects/import-objects/import-objects.component';
import { ImportTypesComponent } from './components/types/import-types/import-types.component';
import { ImportThreatComponent } from './components/threat/threat-import.component';
import { ImportVulnerabilityComponent } from './components/vulnerability/vulnerability-import.component';
import { ImportRiskComponent } from './components/risk/risk-import.component';
import { ImportControlMeasureComponent } from './components/control-measure/control-measure-import.component';
/* ------------------------------------------------------------------------------------------------------------------ */

const routes: Routes = [
    {
        path: '',
        pathMatch: 'full',
        canActivate: [PermissionGuard],
        data: {
            breadcrumb: 'Overview'
        },
        component: ImportComponent
    },
    {
        path: 'object',
        canActivate: [PermissionGuard],
        data: {
            breadcrumb: 'Object',
            right: 'base.import.object.*'
        },
        component: ImportObjectsComponent
    },
    {
        path: 'type',
        canActivate: [PermissionGuard],
        data: {
            breadcrumb: 'Type',
            right: 'base.import.type.*'
        },
        component: ImportTypesComponent
    },
    {
        path: 'threat',
        canActivate: [PermissionGuard],
        data: {
            breadcrumb: 'Threats',
            right: 'base.isms.import.add'
        },
        component: ImportThreatComponent
    },
    {
        path: 'vulnerability',
        canActivate: [PermissionGuard],
        data: {
            breadcrumb: 'Vulnerabilities',
            right: 'base.isms.import.add'
        },
        component: ImportVulnerabilityComponent
    },
    {
        path: 'risk',
        canActivate: [PermissionGuard],
        data: {
            breadcrumb: 'Risks',
            right: 'base.isms.import.add'
        },
        component: ImportRiskComponent
    },
    {
        path: 'control-measure',
        canActivate: [PermissionGuard],
        data: {
            breadcrumb: 'Controls',
            right: 'base.isms.import.add'
        },
        component: ImportControlMeasureComponent
    }
];

@NgModule({
    imports: [RouterModule.forChild(routes)],
    exports: [RouterModule]
})
export class ImportRoutingModule {}
