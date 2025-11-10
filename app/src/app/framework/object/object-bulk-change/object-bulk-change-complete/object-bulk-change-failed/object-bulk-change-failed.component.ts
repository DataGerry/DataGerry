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

import { Component, Input, OnInit, TemplateRef, ViewChild } from '@angular/core';
import { Column } from '../../../../../layout/table/table.types';

@Component({
    selector: 'cmdb-object-bulk-change-failed',
    templateUrl: './object-bulk-change-failed.component.html',
    styleUrls: ['./object-bulk-change-failed.component.scss'],
    standalone: false
})
export class ObjectBulkChangeFailedComponent implements OnInit {

  @Input() failedChanges: any[] = [];

  @ViewChild('errorTemplate', {static : true}) errorTemplate: TemplateRef<any>;
  @ViewChild('objectTemplate', {static : true}) objectTemplate: TemplateRef<any>;

  public columns: Column[] = [];

  ngOnInit() {
    this.columns = [
      {
        display: 'Object',
        name: 'public_id',
        data: 'public_id',
      },
      {
        display: 'Error Message',
        name: 'error_message',
        data: 'error_message',
        template: this.errorTemplate
      },
      {
        display: 'Object',
        name: 'object',
        data: 'obj',
        template: this.objectTemplate
      },
      {
        display: 'Response state',
        name: 'status',
        data: 'status',
      }
    ] as Array<Column>;
  }

}
