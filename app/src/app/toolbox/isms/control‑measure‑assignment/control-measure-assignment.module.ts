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
import { TableModule } from 'src/app/layout/table/table.module';
import { ReactiveFormsModule } from '@angular/forms';
import { CoreModule } from 'src/app/core/core.module';
import { NgbModule } from '@ng-bootstrap/ng-bootstrap';
import { ControlMeasureAssignmentAddComponent } from './control‑measure‑assignment-add/control-measure-assignment-add.component';
import { ControlMeasureAssignmentListComponent } from './control‑measure‑assignment-list/control‑measure‑assignment-list.component';
import { AuthModule } from 'src/app/modules/auth/auth.module';

@NgModule({
  declarations: [
    ControlMeasureAssignmentListComponent,
    ControlMeasureAssignmentAddComponent
  ],
  imports: [
    CommonModule,
    TableModule,
    ReactiveFormsModule,
    CoreModule,
    NgbModule,
    AuthModule
  ],
  exports: [
    ControlMeasureAssignmentListComponent
  ]
})
export class ControlMeasureAssignmentModule {}
