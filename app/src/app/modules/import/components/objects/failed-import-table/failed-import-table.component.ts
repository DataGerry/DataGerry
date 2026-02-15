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
* along with this program.  If not, see <https://www.gnu.org/licenses/>.
*/
import { Component, Input, OnInit, TemplateRef, ViewChild } from '@angular/core';

import { Column } from '../../../../../layout/table/table.types';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'cmdb-failed-import-table',
    templateUrl: './failed-import-table.component.html',
    styleUrls: ['./failed-import-table.component.scss'],
    standalone: false
})
export class FailedImportTableComponent implements OnInit {

  @Input() failedImports: any = [];

  @ViewChild('errorTemplate', {static : true}) errorTemplate: TemplateRef<any>;
  @ViewChild('objectTemplate', {static : true}) objectTemplate: TemplateRef<any>;

  public columns: Column[] = [];

/* ------------------------------------------------------------------------------------------------------------------ */
/*                                                     LIFE CYCLE                                                     */
/* ------------------------------------------------------------------------------------------------------------------ */

    ngOnInit() {
        this.columns = [
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
        }
        ] as Array<Column>;
    }
}
