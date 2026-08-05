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

import { NgSelectModule } from '@ng-select/ng-select';

import { SearchRoutingModule } from './search-routing.module';
import { LayoutModule } from '../../layout/layout.module';
import { RenderModule } from '../../framework/render/render.module';
import { TableModule } from '../../layout/table/table.module';

import { SearchComponent } from './search.component';
import { SearchResultComponent } from './components/search-result/search-result.component';
import { SearchResultPreviewComponent } from './components/search-result-preview/search-result-preview.component';
import { SearchResultMatchComponent } from './components/search-result-match/search-result-match.component';
import { SearchResultBarComponent } from './components/search-result-bar/search-result-bar.component';
/* ------------------------------------------------------------------------------------------------------------------ */

@NgModule({
    declarations: [
        SearchComponent,
        SearchResultComponent,
        SearchResultPreviewComponent,
        SearchResultMatchComponent,
        SearchResultBarComponent
    ],
    imports: [
        CommonModule,
        SearchRoutingModule,
        FormsModule,
        LayoutModule,
        ReactiveFormsModule,
        RenderModule,
        NgSelectModule,
        TableModule
    ]
})
export class SearchModule {}