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

import { Component, Input } from '@angular/core';

@Component({
    selector: 'table-info',
    templateUrl: './table-info.component.html',
    styleUrls: ['./table-info.component.scss'],
    standalone: false
})
export class TableInfoComponent {

  /**
   * Select row enabled.
   */
  @Input() public selectEnabled: boolean = false;

  /**
   * Number of selected elements
   */
  @Input() public selected: number = 0;

  /**
   * Number of displayed items on this page.
   */
  @Input() public show: number = 0;

  /**
   * Number of all items for this table.
   */
  @Input() public total: number = 0;

}
