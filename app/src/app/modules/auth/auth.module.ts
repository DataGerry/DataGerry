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
import { CommonModule } from '@angular/common';
import { RouterModule } from '@angular/router';
import { FormsModule, ReactiveFormsModule } from '@angular/forms';

import { SessionTimeoutService } from './services/session-timeout.service';

import { PermissionLinkDirective } from './directives/permission-link.directive';
import { PermissionGuard } from './guards/permission.guard';

import { LoginComponent } from './login/login.component';
import { SessionTimeoutModalComponent } from './modals/session-timeout-modal/session-timeout-modal.component';
import { AuthCallbackComponent } from './callback/auth-callback.component';
import { NgSelectModule } from '@ng-select/ng-select';
import { LayoutModule } from 'src/app/layout/layout.module';
import { CoreModule } from 'src/app/core/core.module';
/* ------------------------------------------------------------------------------------------------------------------ */

@NgModule({
    declarations: [
        LoginComponent,
        PermissionLinkDirective,
        SessionTimeoutModalComponent,
        AuthCallbackComponent
    ],
    exports: [
        PermissionLinkDirective
    ],
    imports: [
        CommonModule,
        FormsModule,
        RouterModule,
        ReactiveFormsModule,
        NgSelectModule,
        // LayoutModule
        CoreModule
    ],
    providers: [
        PermissionGuard,
        SessionTimeoutService
    ]
})
export class AuthModule {
}
