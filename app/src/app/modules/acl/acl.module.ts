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
import { ReactiveFormsModule } from '@angular/forms';
import { RouterModule } from '@angular/router';

import { TableModule } from 'src/app/layout/table/table.module';
import { LayoutModule } from 'src/app/layout/layout.module';

import { AclObjectsTableComponent} from './components/acl-objects-table/acl-objects-table.component';
import { AclObjectPermissionsComponent } from './components/acl-object-permissions/acl-object-permissions.component';
/* ------------------------------------------------------------------------------------------------------------------ */

@NgModule({
    declarations: [
        AclObjectsTableComponent,
        AclObjectPermissionsComponent
    ],
    exports: [
        AclObjectsTableComponent
    ],
    imports: [
        CommonModule,
        TableModule,
        LayoutModule,
        ReactiveFormsModule,
        RouterModule
    ]
})
export class AclModule {
}
