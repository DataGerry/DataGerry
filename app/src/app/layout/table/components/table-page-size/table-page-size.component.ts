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

import {
  ChangeDetectionStrategy,
  Component,
  EventEmitter,
  Input,
  OnDestroy,
  OnInit,
  Output
} from '@angular/core';
import { ReplaySubject } from 'rxjs';
import { UntypedFormControl, UntypedFormGroup } from '@angular/forms';
import { takeUntil } from 'rxjs/operators';

/**
 * Interface for a page length selection.
 */
export interface PageLengthEntry {
  label: string | number;
  value: number;
}

@Component({
  selector: 'table-page-size',
  templateUrl: './table-page-size.component.html',
  styleUrls: ['./table-page-size.component.scss'],
  changeDetection: ChangeDetectionStrategy.Default,
})
export class TablePageSizeComponent implements OnInit, OnDestroy {

  /**
   * Component un-subscriber.
   * @private
   */
  private subscriber: ReplaySubject<void> = new ReplaySubject<void>();

  /**
   * Page size select form group.
   */
  public form: UntypedFormGroup;

  /**
   * The default page size.
   * @private
   */
  private readonly defaultPageSize: number = 10;

  /**
   * A preset of default page sizes.
   * @private
   */
  private readonly defaultPageSizeList: Array<PageLengthEntry> =
    [
      { label: '10', value: 10 },
      { label: '25', value: 25 },
      { label: '50', value: 50 },
      { label: '100', value: 100 },
      { label: '200', value: 200 },
      { label: '500', value: 500 }
    ];

  /**
   * The current page size.
   */
  public pageSize: number = this.defaultPageSize;

  /**
   * The current page size list.
   */
  public pageSizeList: Array<PageLengthEntry> = this.defaultPageSizeList;

  /**
   * Page size input setter.
   * @param size - Value of the current page size.
   */
  @Input('pageSize')
  public set PageSize(size: number) {
    this.pageSize = size || this.defaultPageSize;
    this.form.get('size').setValue(this.pageSize);
  }

  /**
   * Page size list input setter.
   * @param list - A list of all possible page sizes.
   */
  @Input('pageSizeList')
  public set PageSizeList(list: Array<PageLengthEntry>) {
    this.pageSizeList = list || this.defaultPageSizeList;
  }

  /**
   * Page size change event emitter.
   */
  @Output() public pageSizeChange: EventEmitter<number> = new EventEmitter<number>();

  /**
   * Constructor of `TablePageSizeComponent`.
   */
  constructor() {
    this.form = new UntypedFormGroup({
      size: new UntypedFormControl(this.pageSize),
    });
  }

  /**
   * OnInit of `TablePageSizeComponent`.
   * Auto subscribes to size control values changes.
   * Emits changes to pageSizeChange EventEmitter.
   */
  public ngOnInit(): void {
    this.size.valueChanges.pipe(takeUntil(this.subscriber))
      .subscribe((size: number) => this.pageSizeChange.emit(size));
  }

  /**
   * Get the form control of the size selection.
   */
  public get size(): UntypedFormControl {
    return this.form.get('size') as UntypedFormControl;
  }

  /**
   * OnDestroy of `TablePageSizeComponent`.
   * Sends complete call to the component subscriber.
   */
  public ngOnDestroy(): void {
    this.subscriber?.next();
    this.subscriber?.complete();
  }

}
