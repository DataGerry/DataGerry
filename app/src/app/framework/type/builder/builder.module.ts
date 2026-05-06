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

import { DndModule } from 'ngx-drag-drop';
import { NgSelectModule } from '@ng-select/ng-select';
import { NgbDatepickerModule, NgbModalModule, NgbTooltipModule } from '@ng-bootstrap/ng-bootstrap';
import { FontAwesomeModule } from '@fortawesome/angular-fontawesome';

import { RenderModule } from '../../render/render.module';
import { CategoryModule } from '../../category/category.module';
import { LayoutModule } from '../../../layout/layout.module';
import { CoreModule } from 'src/app/core/core.module';

import { BuilderComponent } from './builder.component';
import { TextFieldEditComponent } from './configs/text/text-field-edit.component';
import { SectionFieldEditComponent } from './configs/section/section-field-edit.component';
import { SectionMultiFieldEditComponent } from './configs/section/section-multi-field-edit.component';
import { TextareaEditComponent } from './configs/text/textarea-edit.component';
import { NumberFieldEditComponent } from './configs/number/number-field-edit.component';
import { RefFieldEditComponent } from './configs/special/ref-field-edit.component';
import { LocationFieldEditComponent } from './configs/special/location-field-edit.component';
import { ChoiceFieldEditComponent } from './configs/choice/choice-field-edit.component';
import { CheckFieldEditComponent } from './configs/choice/check-field-edit.component';
import { DateFieldEditComponent } from './configs/date-time/date-field-edit.component';
import { SectionRefFieldEditComponent } from './configs/section/section-ref-field-edit.component';
import { ConfigEditComponent } from './configs/config-edit.component';
import { PreviewModalComponent } from './modals/preview-modal/preview-modal.component';
import { DiagnosticModalComponent } from './modals/diagnostic-modal/diagnostic-modal.component';
import { LocationFieldInUseModalComponent } from './modals/location-field-in-use-modal/location-field-in-use-modal.component';
import { ColorChromeModule } from 'ngx-color/chrome';
/* ------------------------------------------------------------------------------------------------------------------ */

@NgModule({
    imports: [
        CommonModule,
        DndModule,
        FormsModule,
        ReactiveFormsModule,
        RenderModule,
        NgbModalModule,
        NgSelectModule,
        FontAwesomeModule,
        NgbDatepickerModule,
        CategoryModule,
        NgbTooltipModule,
        LayoutModule,
        ColorChromeModule,
        CoreModule
    ],
    declarations: [
        ConfigEditComponent,
        BuilderComponent,
        TextFieldEditComponent,
        NumberFieldEditComponent,
        SectionFieldEditComponent,
        SectionMultiFieldEditComponent,
        TextareaEditComponent,
        RefFieldEditComponent,
        LocationFieldEditComponent,
        ChoiceFieldEditComponent,
        CheckFieldEditComponent,
        DateFieldEditComponent,
        SectionRefFieldEditComponent,
        PreviewModalComponent,
        DiagnosticModalComponent,
        LocationFieldInUseModalComponent
    ],
    exports: [
        BuilderComponent,
        SectionFieldEditComponent,
        ConfigEditComponent
    ]
})
export class BuilderModule { }
