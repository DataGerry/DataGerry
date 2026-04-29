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

* You should have received a copy of the GNU Affero General Public License
* along with this program. If not, see <https://www.gnu.org/licenses/>.
*/
import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ReactiveFormsModule } from '@angular/forms';
import { NgbModule } from '@ng-bootstrap/ng-bootstrap';
import { CoreModule } from 'src/app/core/core.module';
import { TableModule } from 'src/app/layout/table/table.module';
import { AddCategoryModalComponent } from './components/category-add-modal/category-add-modal.component';
import { CategoryFormComponent } from './components/category-form/category-form.component';
import { CategoryOverviewComponent } from './components/category-overview/category-overview.component';
import { ReportCategoryRoutingModule } from './report-category-routing.module';



@NgModule({
    declarations: [
        CategoryOverviewComponent,
        CategoryFormComponent,
        AddCategoryModalComponent
    ],
    imports: [
        CommonModule,
        ReportCategoryRoutingModule,
        TableModule,
        NgbModule,
        ReactiveFormsModule,
        CoreModule    ]
})
export class ReportCategoryModule { }
