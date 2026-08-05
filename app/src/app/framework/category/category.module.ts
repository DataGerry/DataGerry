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
import { FontAwesomeModule } from '@fortawesome/angular-fontawesome';
import { IconPickerModule } from 'ngx-icon-picker';

import { CategoryRoutingModule } from './category-routing.module';
import { LayoutModule } from '../../layout/layout.module';
import { AuthModule } from '../../modules/auth/auth.module';
import { TableModule } from '../../layout/table/table.module';

import { CategoryComponent } from './category.component';
import { CategoryAddComponent } from './category-add/category-add.component';
import { CategoryFormComponent } from './category-form/category-form.component';
import { CategoryEditComponent } from './category-edit/category-edit.component';
import { CategoryTreeComponent } from './components/category-tree/category-tree.component';
import { CategoryNodeComponent } from './components/category-node/category-node.component';
import { AddCategoryModalComponent } from './components/modals/add-category-modal/add-category-modal.component';
import { CategoryViewComponent } from './category-view/category-view.component';
import { DeleteCategoryModalComponent } from './components/modals/delete-category-modal/delete-category-modal.component';
import { CoreModule } from 'src/app/core/core.module';
/* ------------------------------------------------------------------------------------------------------------------ */

@NgModule({
    declarations: [
        CategoryComponent,
        CategoryAddComponent,
        CategoryFormComponent,
        CategoryEditComponent,
        CategoryTreeComponent,
        CategoryNodeComponent,
        AddCategoryModalComponent,
        DeleteCategoryModalComponent,
        CategoryViewComponent
    ],
    imports: [
        CommonModule,
        CategoryRoutingModule,
        DndModule,
        ReactiveFormsModule,
        LayoutModule,
        NgSelectModule,
        FontAwesomeModule,
        FormsModule,
        IconPickerModule,
        AuthModule,
        TableModule,
        CoreModule
    ]
})
export class CategoryModule {}