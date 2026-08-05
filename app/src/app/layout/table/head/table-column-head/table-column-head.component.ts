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

import {
  ChangeDetectionStrategy,
  Component,
  EventEmitter,
  HostBinding,
  HostListener,
  Input,
  Output,
  ViewEncapsulation
} from '@angular/core';
import { Column, Sort, SortDirection } from '../../table.types';

@Component({
    selector: 'th[table-column-head]',
    templateUrl: './table-column-head.component.html',
    styleUrls: ['./table-column-head.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    encapsulation: ViewEncapsulation.Emulated,
    standalone: false
})
export class TableColumnHeadComponent {

  // noinspection JSMismatchedCollectionQueryUpdate
  @HostBinding('class') public cssClasses: Array<string>;
  @HostBinding('class.sortable') public sortable: boolean = false;
  @HostBinding('class.hidden') @Input() public hidden: boolean = false;
  @HostBinding('class.sorting-asc') public sortAsc: boolean = true;
  @HostBinding('class.sorting-desc') public sortDesc: boolean = true;

  /**
   * Column of this head element.
   */
  public column: Column;

  /**
   * Column setter. Also sets the `hidden`, `sortable` and `cssClasses`
   * property from the Column element.
   * @param c Column
   */
  @Input('column')
  public set Column(c: Column) {
    this.column = c;
    this.hidden = this.column.hidden;
    this.sortable = this.column.sortable || false;
    this.cssClasses = this.column.cssClasses || [];
  }

  /**
   * Sort order of this element.
   */
  @Input() public order: SortDirection = SortDirection.NONE;

  /**
   * Event Emitter when the sort order and selection was changed.
   */
  @Output() public sortChange: EventEmitter<Sort> = new EventEmitter<Sort>();

  /**
   * Is this the selected sort column.
   */
  public sortActivated: boolean = false;

  /**
   * Sort Activation setter.
   * @param value
   */
  @Input('sortActivated')
  public set SortActivated(value: boolean) {
    this.onSelectedChange(value);
  }

  /**
   * Change the activation status.
   * @param value
   */
  public onSelectedChange(value: boolean) {
    this.sortActivated = value;
    if (!this.sortActivated) {
      this.order = SortDirection.NONE;
      this.sortAsc = false;
      this.sortDesc = false;
    } else {
      this.order = this.reverseOrder(this.order);
      if (this.order === SortDirection.ASCENDING) {
        this.sortDesc = false;
        this.sortAsc = true;
      } else if (this.order === SortDirection.DESCENDING) {
        this.sortDesc = true;
        this.sortAsc = false;
      } else {
        this.sortAsc = false;
        this.sortDesc = false;
      }
    }
  }

  /**
   * Auto select this column for sort when clicked.
   * Reverse the order on reclick.
   *
   * @param e
   */
  @HostListener('click', ['$event'])
  public onClick(e) {
    if (this.column && this.column.sortable && this.sortable) {
      this.onSelectedChange(true);
      const sort = {
        name: this.column.name,
        order: this.order
      } as Sort;
      this.sortChange.emit(sort);
    }
  }


  /**
   * Swap the sort order on call.
   * @param direction
   */
  public reverseOrder(direction: SortDirection): SortDirection {
    if (direction === SortDirection.DESCENDING) {
      return SortDirection.ASCENDING;
    } else {
      return SortDirection.DESCENDING;
    }
  }

}
