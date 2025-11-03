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
*
* You should have received a copy of the GNU Affero General Public License
* along with this program.  If not, see <https://www.gnu.org/licenses/>.
*/
import { NgModule } from '@angular/core';
import { RouterModule, Routes } from '@angular/router';
import { PersonListComponent } from './person-list/person-list.component';
import { PersonAddEditComponent } from './person-add/person-add-edit.component';

const routes: Routes = [

    {
        path: '',
        children: [
            {
                path: '', component: PersonListComponent,
                data: {
                    breadcrumb: 'Persons',
                    right: 'base.user-management.person.view'
                },
            },
            {
                path: 'add', component: PersonAddEditComponent,
                data: {
                    breadcrumb: 'Add Person',
                    right: 'base.user-management.person.add'
                },
            },
            {
                path: 'view', component: PersonAddEditComponent,
                data: {
                    breadcrumb: 'View Person',
                    right: 'base.user-management.person.view'
                },
            },
            {
                path: 'edit', component: PersonAddEditComponent,
                data: {
                    breadcrumb: 'Edit Person',
                    right: 'base.user-management.person.edit'
                },
            }
        ]
    },
];

@NgModule({
    imports: [RouterModule.forChild(routes)],
    exports: [RouterModule]
})
export class PersonRoutingModule { }
