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
import { FormsModule, ReactiveFormsModule } from '@angular/forms';

import { ArchwizardModule } from '@rg-software/angular-archwizard';
import { QRCodeComponent } from 'angularx-qrcode';
import { NgSelectModule } from '@ng-select/ng-select';
import { NgbModule } from '@ng-bootstrap/ng-bootstrap';
import { FontAwesomeModule } from '@fortawesome/angular-fontawesome';
import { IconPickerModule } from 'ngx-icon-picker';

import { AuthModule } from '../../modules/auth/auth.module';
import { TypeRoutingModule } from './type-routing.module';
import { LayoutModule } from '../../layout/layout.module';
import { RenderModule } from '../render/render.module';
import { BuilderModule } from './builder/builder.module';
import { TableModule } from '../../layout/table/table.module';
import { UsersModule } from '../../management/users/users.module';

import { TypeAddComponent } from './type-add/type-add.component';
import { TypeBuilderComponent } from './type-builder/type-builder.component';
import { TypeBasicStepComponent } from './type-builder/type-basic-step/type-basic-step.component';
import { TypeFieldsStepComponent } from './type-builder/type-fields-step/type-fields-step.component';
import { TypeEditComponent } from './type-edit/type-edit.component';
import { TypeMetaStepComponent } from './type-builder/type-meta-step/type-meta-step.component';
import { TypeDeleteComponent, TypeDeleteConfirmModalComponent } from './type-delete/type-delete.component';
import { TypeComponent } from './type.component';
import { CleanupModalComponent } from './modals/cleanup-modal/cleanup-modal.component';
import { CleanButtonComponent } from './components/clean-button/clean-button.component';
import { TypeAclStepComponent } from './type-builder/type-acl-step/type-acl-step.component';
import { GroupsAclTabsComponent } from './type-builder/type-acl-step/groups-acl-tabs/groups-acl-tabs.component';
import { TypeTableActionsComponent } from './components/type-table-actions/type-table-actions.component';
import {
  TypeBuilderStepComponent,
  TypeBuilderStepValidStatusComponent
} from './type-builder/type-builder-step.component';
import { TypePreviewStepComponent } from './type-builder/type-preview-step/type-preview-step.component';
import { CoreModule } from 'src/app/core/core.module';
/* ------------------------------------------------------------------------------------------------------------------ */

@NgModule({
    declarations: [
        TypeAddComponent,
        TypeBasicStepComponent,
        TypeFieldsStepComponent,
        TypeBuilderComponent,
        TypeEditComponent,
        TypeMetaStepComponent,
        TypeDeleteComponent,
        TypeDeleteConfirmModalComponent,
        TypeComponent,
        CleanupModalComponent,
        CleanButtonComponent,
        TypeAclStepComponent,
        GroupsAclTabsComponent,
        TypeTableActionsComponent,
        TypeBuilderStepComponent,
        TypeBuilderStepValidStatusComponent,
        TypePreviewStepComponent,
    ],
    imports: [
        CommonModule,
        TypeRoutingModule,
        LayoutModule,
        ReactiveFormsModule,
        ArchwizardModule,
        QRCodeComponent,
        NgSelectModule,
        RenderModule,
        BuilderModule,
        FormsModule,
        NgbModule,
        FontAwesomeModule,
        AuthModule,
        TableModule,
        IconPickerModule,
        UsersModule,
        CoreModule
    ]
})
export class TypeModule {}