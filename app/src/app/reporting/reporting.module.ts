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
import { ReportingRoutingModule } from './reporting-routing.module';

// Import the feature modules
import { ReportModule } from './report/report.module';
import { ReportCategoryModule } from './category/report-category.module';
import { RunReportComponent } from './report/components/run-report/run-report.component';
import { TableModule } from "../layout/table/table.module";
import { CoreModule } from '../core/core.module';

@NgModule({
    declarations: [
        RunReportComponent,
    ],
    imports: [
        CommonModule,
        ReportingRoutingModule, // Main routing module for reporting
        ReportModule,
        ReportCategoryModule,
        TableModule,
        CoreModule
    ]
})
export class ReportingModule { }
