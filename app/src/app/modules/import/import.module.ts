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
import { FontAwesomeModule } from '@fortawesome/angular-fontawesome';
import { DndModule } from 'ngx-drag-drop';
import { NgbTooltipModule } from '@ng-bootstrap/ng-bootstrap';

import { ImportRoutingModule } from './import-routing.module';
import { LayoutModule } from '../../layout/layout.module';
import { TypeModule } from '../../framework/type/type.module';
import { RenderModule } from '../../framework/render/render.module';
import { CategoryModule } from '../../framework/category/category.module';
import { TableModule } from '../../layout/table/table.module';
import { AuthModule } from '../auth/auth.module';

import { MappingControlPipe } from './pipes/mapping-control.pipe';

import { ImportComponent } from './import.component';
import { ImportObjectsComponent } from './components/objects/import-objects/import-objects.component';
import { FileConfigComponent } from './components/objects/file-config/file-config.component';
import { CsvConfigComponent } from './components/objects/csv-config/csv-config.component';
import { JsonConfigComponent } from './components/objects/json-config/json-config.component';
import { ImportTypesComponent } from './components/types/import-types/import-types.component';
import { SelectFileComponent } from './components/objects/select-file/select-file.component';
import { ImportConfigComponent } from './components/objects/import-config/import-config.component';
import { TypeMappingComponent } from './components/objects/type-mapping/type-mapping.component';
import { JsonMappingComponent } from './components/objects/json-mapping/json-mapping.component';
import { TypeMappingBaseComponent } from './components/objects/type-mapping/type-mapping-base.component';
import { CsvMappingComponent } from './components/objects/csv-mapping/csv-mapping.component';
import { SelectFileDragDropComponent } from './components/types/select-file-drag-drop/select-file-drag-drop.component';
import { TypePreviewComponent } from './components/types/type-preview/type-preview.component';
import { ImportTypeCompleteComponent } from './components/types/import-type-complete/import-type-complete.component';
import { ImportCompleteComponent } from './components/objects/import-complete/import-complete.component';
import { FailedImportTableComponent } from './components/objects/failed-import-table/failed-import-table.component';
import { CoreModule } from 'src/app/core/core.module';
import { ImportThreatComponent } from './components/threat/threat-import.component';
import { ImportVulnerabilityComponent } from './components/vulnerability/vulnerability-import.component';
import { ImportControlMeasureComponent } from './components/control-measure/control-measure-import.component';
import { ImportRiskComponent } from './components/risk/risk-import.component';
import { ImportInstructionsComponent } from './components/import-instructions/import-instructions.component';
import { ImportSummaryModalComponent } from './components/import-summary-dialog/import-summary-dialog.component';
/* ------------------------------------------------------------------------------------------------------------------ */

@NgModule({
    declarations: [
        ImportComponent,
        ImportObjectsComponent,
        SelectFileComponent,
        FileConfigComponent,
        CsvConfigComponent,
        JsonConfigComponent,
        ImportTypesComponent,
        ImportConfigComponent,
        TypeMappingComponent,
        JsonMappingComponent,
        TypeMappingBaseComponent,
        CsvMappingComponent,
        MappingControlPipe,
        SelectFileDragDropComponent,
        TypePreviewComponent,
        ImportTypeCompleteComponent,
        ImportCompleteComponent,
        FailedImportTableComponent,
        ImportThreatComponent,
        ImportVulnerabilityComponent,
        ImportRiskComponent,
        ImportControlMeasureComponent,
        ImportInstructionsComponent,
        ImportSummaryModalComponent
    ],
    imports: [
        CommonModule,
        LayoutModule,
        ImportRoutingModule,
        DndModule,
        ArchwizardModule,
        ReactiveFormsModule,
        NgSelectModule,
        TypeModule,
        FontAwesomeModule,
        RenderModule,
        NgbTooltipModule,
        FormsModule,
        CategoryModule,
        TableModule,
        AuthModule,
        CoreModule
    ]
})
export class ImportModule {}
