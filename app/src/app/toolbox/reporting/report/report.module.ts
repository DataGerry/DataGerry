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
import { FormsModule, ReactiveFormsModule } from '@angular/forms';
import { ReportRoutingModule } from './report-routing.module';
import { QueryBuilderModule } from 'shout-angular-query-builder';


import { ReportOverviewComponent } from './components/report-overview/report-overview.component';
import { CreateReportComponent } from './components/create-report/create-report.component';
import { FilterBuilderComponent } from './components/filter-builder/filter-builder.component';
import { NgSelectModule } from '@ng-select/ng-select';
import { TableModule } from 'src/app/layout/table/table.module';
import { LayoutModule } from 'src/app/layout/layout.module';
import { CoreModule } from 'src/app/core/core.module';

@NgModule({
    declarations: [
        ReportOverviewComponent,
        CreateReportComponent,
        FilterBuilderComponent
    ],
    imports: [
        CommonModule,
        ReportRoutingModule,
        FormsModule,
        ReactiveFormsModule,
        QueryBuilderModule,
        NgSelectModule,
        TableModule,
        CoreModule
    ],
    exports: [
        FilterBuilderComponent
    ]
})
export class ReportModule { }
