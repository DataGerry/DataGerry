/*
* DATAGERRY - OpenSource Enterprise CMDB
* Copyright (C) 2025 becon GmbH
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
import { TableComponent } from './table.component';
import { FormsModule, ReactiveFormsModule } from '@angular/forms';
import { TableSearchComponent } from './components/table-search/table-search.component';
import { TablePageSizeComponent } from './components/table-page-size/table-page-size.component';
import { TablePaginationComponent } from './components/table-pagination/table-pagination.component';
import { TableFootDirective } from './foot/table-foot.directive';
import { TableHeadDirective } from './head/table-head.directive';
import { TableDirective } from './table.directive';
import { TableBodyDirective } from './body/table-body.directive';
import { TableColumnHeadComponent } from './head/table-column-head/table-column-head.component';
import { TableInfoComponent } from './components/table-info/table-info.component';
import { TableCellComponent } from './body/table-cell/table-cell.component';
import { TableRowDirective } from './body/table-row.directive';
import { TableColumnToggleComponent } from './components/table-column-toggle/table-column-toggle.component';
import { TableLoadingComponent } from './components/table-loading/table-loading.component';
import { TableStateComponent } from './components/table-states/table-state.component';
import { TableColumnSearchComponent } from './head/table-column-search/table-column-search.component';
import { DragDropModule } from '@angular/cdk/drag-drop';
import { AnchorDetectPipe } from './pipes/anchor-detect.pipe';


@NgModule({
  declarations: [
    TableComponent, TableSearchComponent, TablePageSizeComponent,
    TablePaginationComponent, TableFootDirective, TableHeadDirective, TableDirective,
    TableBodyDirective, TableColumnHeadComponent, TableInfoComponent, TableCellComponent,
    TableRowDirective, TableColumnToggleComponent, TableLoadingComponent, TableStateComponent,
    TableColumnSearchComponent, AnchorDetectPipe],
    exports: [
        TableComponent,
        TablePaginationComponent,
        AnchorDetectPipe
    ],
  imports: [
    CommonModule,
    FormsModule,
    ReactiveFormsModule,
    DragDropModule
  ]
})
export class TableModule {
}
