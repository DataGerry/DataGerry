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
import { cloudModeChildGuard } from '../modules/auth/guards/cloud-mode.guard';

import { SettingsComponent } from './settings.component';
import { DateSettingsComponent } from './date-settings/date-settings.component';
/* ------------------------------------------------------------------------------------------------------------------ */

const routes: Routes = [
    {
        path: '',
        canActivate: [PermissionGuard],
        data: {
            breadcrumb: 'Overview',
            right: 'base.system.view'
        },
        component: SettingsComponent
    },
    {
        path: 'system',
        canActivateChild: [PermissionGuard, cloudModeChildGuard],
        data: {
            breadcrumb: 'System'
        },
        loadChildren: () => import('./system/system.module').then(m => m.SystemModule)
    },
    {
        path: 'logs',
        data: {
            breadcrumb: 'Logs'
        },
        loadChildren: () => import('./log-settings/log-settings.module').then(m => m.LogSettingsModule)
    },
    {
        path: 'auth',
        canActivateChild: [PermissionGuard, cloudModeChildGuard],
        data: {
            breadcrumb: 'Authentication'
        },
        loadChildren: () => import('./auth-settings/auth-settings.module').then(m => m.AuthSettingsModule)
    },
    {
        path: 'regional-settings',
        data: {
            breadcrumb: 'Regional Settings',
            right: 'base.system.edit'
        },
        component: DateSettingsComponent
    }
];

@NgModule({
    imports: [RouterModule.forChild(routes)],
    exports: [RouterModule]
})
export class SettingsRoutingModule { }