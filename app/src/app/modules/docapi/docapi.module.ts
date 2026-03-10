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

import { EditorModule, TINYMCE_SCRIPT_SRC } from '@tinymce/tinymce-angular';
import { NgSelectModule } from '@ng-select/ng-select';
import { ArchwizardModule } from '@rg-software/angular-archwizard';
import { FontAwesomeModule } from '@fortawesome/angular-fontawesome';

import { AuthModule } from '../auth/auth.module';
import { DocapiRoutingModule } from './docapi-routing.module';
import { LayoutModule } from '../../layout/layout.module';
import { TableModule } from '../../layout/table/table.module';

import { DocapiListComponent } from './components/docapi-list/docapi-list.component';
import { DocapiAddComponent } from './components/docapi-add/docapi-add.component';
import { DocapiBuilderContentStepComponent } from './components/docapi-builder-content-step/docapi-builder-content-step.component';
import { DocapiBuilderComponent } from './components/docapi-builder/docapi-builder.component';
import { DocapiBuilderTypeStepObjectComponent } from './components/docapi-builder-type-step-object/docapi-builder-type-step-object.component';
import { DocapiBuilderTypeStepComponent } from './components/docapi-builder-type-step/docapi-builder-type-step.component';
import { DocapiBuilderSettingsStepComponent } from './components/docapi-builder-settings-step/docapi-builder-settings-step.component';
import { DocapiEditComponent } from './components/docapi-edit/docapi-edit.component';
import { DocapiBuilderTypeStepBaseComponent } from './components/docapi-builder-type-step-base/docapi-builder-type-step-base.component';
import { DocapiBuilderStyleStepComponent } from './components/docapi-builder-style-step/docapi-builder-style-step.component';
import { ExternalObjectSelectorModalComponent } from './components/external-object-selector-modal/external-object-selector-modal.component';
import { RelationTemplateSelectorModalComponent } from './components/relation-template-selector-modal/relation-template-selector-modal.component';
import { ReportTemplateSelectorModalComponent } from './components/report-template-selector-modal/report-template-selector-modal.component';
import { CoreModule } from 'src/app/core/core.module';
import { RunReportModule } from 'src/app/toolbox/reporting/report/run-report.module';
import { DocapiPreviewObjectModalComponent } from './components/docapi-preview-object-modal/docapi-preview-object-modal.component';
import { DocapiPageMarginsModalComponent } from './components/docapi-page-margins-modal/docapi-page-margins-modal.component';
/* ------------------------------------------------------------------------------------------------------------------ */
@NgModule({
    declarations: [
        DocapiListComponent,
        DocapiBuilderComponent,
        DocapiAddComponent,
        DocapiBuilderSettingsStepComponent,
        DocapiBuilderContentStepComponent,
        DocapiEditComponent,
        DocapiBuilderTypeStepComponent,
        DocapiBuilderTypeStepObjectComponent,
        DocapiBuilderTypeStepBaseComponent,
        DocapiBuilderStyleStepComponent,
        ExternalObjectSelectorModalComponent,
        RelationTemplateSelectorModalComponent,
        ReportTemplateSelectorModalComponent,
        DocapiPreviewObjectModalComponent,
        DocapiPageMarginsModalComponent
    ],
    imports: [
        CommonModule,
        AuthModule,
        DocapiRoutingModule,
        ReactiveFormsModule,
        EditorModule,
        NgSelectModule,
        ArchwizardModule,
        LayoutModule,
        TableModule,
        FontAwesomeModule,
        FormsModule,
        CoreModule,
        RunReportModule
    ],
    providers: [
        {
            provide: TINYMCE_SCRIPT_SRC, useValue: 'tinymce/tinymce.min.js'
        }
    ]
})
export class DocapiModule {}
