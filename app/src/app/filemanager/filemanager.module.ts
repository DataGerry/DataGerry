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
* along with this program.  If not, see <https://www.gnu.org/licenses/>.
*/

import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';
import { LayoutModule } from '../layout/layout.module';
import { FileexplorerModule } from '../layout/components/file-explorer/fileexplorer.module';
import { FilemanagerRoutingModule } from './filemanager-routing.module';
import { FilemanagerComponent } from './filemanager.component';

@NgModule({
  declarations: [
    FilemanagerComponent
  ],
  imports: [
    CommonModule,
    LayoutModule,
    FilemanagerRoutingModule,
    FileexplorerModule
  ]
})
export class FilemanagerModule { }
