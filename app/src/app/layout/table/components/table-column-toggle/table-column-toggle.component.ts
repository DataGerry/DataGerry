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

import { Component, EventEmitter, Input, Output } from '@angular/core';
import { Column } from '../../table.types';

@Component({
    selector: 'table-column-toggle',
    templateUrl: './table-column-toggle.component.html',
    styleUrls: ['./table-column-toggle.component.scss'],
    standalone: false
})
export class TableColumnToggleComponent {

  /**
   * Column definitions from the table.
   */
  @Input() public columns: Array<Column> = [];

  /**
   * Visibility change emitter.
   */
  @Output() public columnVisibilityChange: EventEmitter<Column> = new EventEmitter<Column>();

  /**
   * Visibility change emitter.
   */
  @Output() public columnsReset: EventEmitter<void> = new EventEmitter<void>();

  /**
   * Toggle the hidden property of a column.
   * The Event interface prevents further propagation of the current event in the capturing and bubbling phases.
   * @param c
   * @param event
   */
  public toggleColumn(c: Column, event: Event): Column {
    event.stopPropagation();
    c.hidden = !c.hidden;
    this.columnVisibilityChange.emit(c);
    return c;
  }

}
