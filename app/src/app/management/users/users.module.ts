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
import { CommonModule } from '@angular/common';
import { ReactiveFormsModule } from '@angular/forms';

import { FontAwesomeModule } from '@fortawesome/angular-fontawesome';

import { AuthModule } from '../../modules/auth/auth.module';
import { UsersRoutingModule } from './users-routing.module';
import { PasswordStrengthMeterModule } from '../../layout/password-strength-meter/password-strength-meter.module';
import { LayoutModule } from '../../layout/layout.module';
import { TableModule } from '../../layout/table/table.module';
import { AclModule } from 'src/app/modules/acl/acl.module';
import { RenderModule } from '../../framework/render/render.module';
import { CoreModule } from 'src/app/core/core.module';

import { UserViewComponent } from './user-view/user-view.component';
import { UsersPasswdModalComponent } from './modals/users-passwd-modal/users-passwd-modal.component';
import { UsersComponent } from './users.component';
import { UserHeadlineComponent } from './components/user-headline/user-headline.component';
import { UserDisplayNameComponent } from './components/user-display-name/user-display-name.component';
import { UserImageComponent } from './components/user-image/user-image.component';
import { UserDisplayComponent } from './components/user-display/user-display.component';
import { UserFormComponent } from './components/user-form/user-form.component';
import { UserAddComponent } from './user-add/user-add.component';
import { UserEditComponent } from './user-edit/user-edit.component';
import { UserDeleteComponent } from './user-delete/user-delete.component';
import { UserCompactComponent } from './components/user-compact/user-compact.component';
import { UserTableActionsComponent } from './components/user-table-actions/user-table-actions.component';
import { UserTableGroupCellComponent } from './components/user-table-group-cell/user-table-group-cell.component';
import { UserTableListComponent } from './components/user-table-list/user-table-list.component';
/* ------------------------------------------------------------------------------------------------------------------ */

@NgModule({
    declarations: [
        UserViewComponent,
        UsersPasswdModalComponent,
        UsersComponent,
        UserImageComponent,
        UserHeadlineComponent,
        UserDisplayNameComponent,
        UserDisplayComponent,
        UserFormComponent,
        UserAddComponent,
        UserEditComponent,
        UserDeleteComponent,
        UserCompactComponent,
        UserTableActionsComponent,
        UserTableGroupCellComponent,
        UserTableListComponent
    ],
    exports: [
        UserImageComponent,
        UserDisplayComponent,
        UserCompactComponent,
        UserTableListComponent
    ],
    imports: [
        CommonModule,
        UsersRoutingModule,
        PasswordStrengthMeterModule,
        ReactiveFormsModule,
        LayoutModule,
        FontAwesomeModule,
        AuthModule,
        TableModule,
        AclModule,
        RenderModule,
        CoreModule
    ]
})
export class UsersModule {}