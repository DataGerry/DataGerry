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
import { FormsModule, ReactiveFormsModule } from '@angular/forms';

import { DndModule } from 'ngx-drag-drop';
import { NgSelectModule } from '@ng-select/ng-select';
import { NgbDatepickerModule, NgbModalModule, NgbTooltipModule } from '@ng-bootstrap/ng-bootstrap';
import { FontAwesomeModule } from '@fortawesome/angular-fontawesome';
import { ColorChromeModule } from 'ngx-color/chrome';

import { RenderModule } from '../../render/render.module';
import { CategoryModule } from '../../category/category.module';
import { LayoutModule } from '../../../layout/layout.module';
import { CoreModule } from 'src/app/core/core.module';
import { BuilderKernelModule } from 'src/app/framework/builder/builder-kernel.module';
import { BuilderPaletteComponent } from 'src/app/framework/builder/palette/builder-palette.component';

import { BuilderComponent } from './builder.component';
/* ------------------------------------------------------------------------------------------------------------------ */

/**
 * The type builder's drag-and-drop canvas. Everything reusable lives in BuilderKernelModule.
 */
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
        CoreModule,
        BuilderKernelModule,
        BuilderPaletteComponent
    ],
    declarations: [
        BuilderComponent
    ],
    exports: [
        BuilderComponent,
        BuilderKernelModule
    ]
})
export class TypeBuilderCanvasModule { }
