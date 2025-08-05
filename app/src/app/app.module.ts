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
import { BrowserModule } from '@angular/platform-browser';
import { NgModule } from '@angular/core';
import { CommonModule, DatePipe } from '@angular/common';
import { HTTP_INTERCEPTORS, provideHttpClient, withInterceptorsFromDi } from '@angular/common/http';
import { BrowserAnimationsModule } from '@angular/platform-browser/animations';

import { FontAwesomeModule } from '@fortawesome/angular-fontawesome';

import { LayoutModule } from './layout/layout.module';
import { ToastModule } from './layout/toast/toast.module';
import { AppRoutingModule } from './app-routing.module';
import { MainModule } from './modules/main/main.module';
import { AuthModule } from './modules/auth/auth.module';
import { RenderModule } from './framework/render/render.module';
import { UsersModule } from './management/users/users.module';
import { ObjectModule } from './framework/object/object.module';
import { TableModule } from './layout/table/table.module';

import { PreviousRouteService } from './services/previous-route.service';
import { RequestCacheService } from './services/request-cache.service';
import { SessionTimeoutService } from './modules/auth/services/session-timeout.service';
import { TreeManagerService } from './services/tree-manager.service';
import { ObjectService } from './framework/services/object.service';

import { HttpErrorInterceptor } from './modules/error/interceptors/http-error.interceptor';
import { BasicAuthInterceptor } from './modules/auth/interceptors/basic-auth.interceptor';
import { APICachingInterceptor } from './services/api-cache.interceptor';

import { DateFormatterPipe } from './layout/pipes/date-formatter.pipe';

import { AppComponent } from './app.component';
import { DashboardComponent } from './components/dashboard/dashboard.component';
import { CoreModule } from './core/core.module';
/* ------------------------------------------------------------------------------------------------------------------ */

@NgModule({ declarations: [
        AppComponent,
        DashboardComponent
    ],
    exports: [
        BrowserModule
    ],
    bootstrap: [
        AppComponent
    ], imports: [CommonModule,
        BrowserModule,
        BrowserAnimationsModule,
        MainModule,
        AuthModule,
        FontAwesomeModule,
        RenderModule,
        UsersModule,
        ObjectModule,
        TableModule,
        LayoutModule,
        ToastModule,
        AppRoutingModule,
        CoreModule], providers: [
        PreviousRouteService,
        DatePipe,
        DateFormatterPipe,
        SessionTimeoutService,
        RequestCacheService,
        TreeManagerService,
        ObjectService,
        { provide: HTTP_INTERCEPTORS, useClass: BasicAuthInterceptor, multi: true },
        { provide: HTTP_INTERCEPTORS, useClass: HttpErrorInterceptor, multi: true },
        { provide: HTTP_INTERCEPTORS, useClass: APICachingInterceptor, multi: true },
        provideHttpClient(withInterceptorsFromDi())
    ] })
export class AppModule {}
