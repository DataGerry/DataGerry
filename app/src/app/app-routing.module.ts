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
* along with this program.  If not, see <https://www.gnu.org/licenses/>.
*/
import { NgModule } from '@angular/core';
import { Routes, RouterModule, PreloadAllModules } from '@angular/router';

import { AuthGuard } from './modules/auth/guards/auth.guard';

import { LoginComponent } from './modules/auth/login/login.component';
import { AuthCallbackComponent } from './modules/auth/callback/auth-callback.component';
/* ------------------------------------------------------------------------------------------------------------------ */

const routes: Routes = [
    {
        path: 'connect',
        data: {
            view: 'embedded'
        },
        loadChildren: () => import('./modules/connect/connect.module').then(m => m.ConnectModule)
    },
    {
        path: 'auth/callback',
        component: AuthCallbackComponent
    },
    {
        path: 'auth',
        data: {
            view: 'embedded'
        },
        component: LoginComponent
    },
    {
        path: '',
        canActivate: [AuthGuard],
        canActivateChild: [AuthGuard],
        loadChildren: () => import('./modules/main/main.module').then(m => m.MainModule)
    },
    {
        path: '**',
        redirectTo: 'error/404'
    }
];

@NgModule({
    imports: [
        RouterModule.forRoot(routes, { preloadingStrategy: PreloadAllModules, enableTracing: false })
    ],
    exports: [
        RouterModule
    ]
})
export class AppRoutingModule { }
