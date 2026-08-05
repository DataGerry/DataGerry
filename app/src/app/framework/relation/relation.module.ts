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
import { NgSelectModule } from '@ng-select/ng-select';
import { NgbModule } from '@ng-bootstrap/ng-bootstrap';
import { FontAwesomeModule } from '@fortawesome/angular-fontawesome';
import { IconPickerModule } from 'ngx-icon-picker';

import { AuthModule } from '../../modules/auth/auth.module';
import { LayoutModule } from '../../layout/layout.module';
import { RenderModule } from '../render/render.module';
import { BuilderModule } from './builder/builder.module';
import { TableModule } from '../../layout/table/table.module';
import { UsersModule } from '../../management/users/users.module';


import { CoreModule } from 'src/app/core/core.module';

import { RelationBuilderStepComponent, RelationBuilderStepValidStatusComponent } from './relation-builder/relation-builder-step.component';
import { RelationPreviewStepComponent } from './relation-builder/relation-preview-step/relation-preview-step.component';
import { RelationAddComponent } from './relation-add/relation-add.component';
import { RelationComponent } from './relation.component';
import { RelationDeleteConfirmModalComponent } from './relation-delete/relation-delete.component';
import { RelationBuilderComponent } from './relation-builder/relation-builder.component';
import { RelationBasicStepComponent } from './relation-builder/relation-basic-step/relation-basic-step.component';

import { RelationFieldsStepComponent } from './relation-builder/relation-fields-step/relation-fields-step.component';
import { RelationRoutingModule } from './relation-routing.module';
import { MatTooltipModule } from '@angular/material/tooltip';
import { RelationEditComponent } from './relation-edit/relation-edit.component';
import { RelationTableActionsComponent } from './components/relation-table-actions/relation-table-actions.component';

/* ------------------------------------------------------------------------------------------------------------------ */

@NgModule({
    declarations: [
        RelationAddComponent,
        RelationBasicStepComponent,
        RelationBuilderComponent,
        RelationEditComponent,
        RelationDeleteConfirmModalComponent,
        RelationDeleteConfirmModalComponent,
        RelationComponent,
        RelationTableActionsComponent,
        RelationBuilderStepComponent,
        RelationBuilderStepValidStatusComponent,
        RelationPreviewStepComponent,
        RelationFieldsStepComponent
    ],
    imports: [
        CommonModule,
        RelationRoutingModule,
        LayoutModule,
        ReactiveFormsModule,
        ArchwizardModule,
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
        CoreModule,
        MatTooltipModule
    ]
})
export class RelationModule {}