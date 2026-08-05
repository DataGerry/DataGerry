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

import { Component, EventEmitter, Input, OnChanges, OnInit, Output, SimpleChanges } from '@angular/core';

/**
 * Pager interface.
 */
export interface Pager {
  /**
   * Total number of items.
   */
  totalItems: number;

  /**
   * Current displayed page number.
   */
  currentPage: number;

  /**
   * Number of items displayed on the page.
   */
  pageSize: number;

  /**
   * Total number of pages.
   * Should be equal to round totalItems / pageSize.
   */
  totalPages: number;

  /**
   * First page in pagination.
   */
  startPage: number;

  /**
   * Last page in pagination.
   */
  endPage: number;

  /**
   * Index of first page in pagination.
   */
  startIndex: number;

  /**
   * Index last page in pagination.
   */
  endIndex: number;

  /**
   * Array of numbered pages for iteration.
   * Used in ngFor.
   */
  pages: Array<number>;
}

@Component({
    selector: 'table-pagination',
    templateUrl: './table-pagination.component.html',
    styleUrls: ['./table-pagination.component.scss'],
    standalone: false
})
export class TablePaginationComponent implements OnInit, OnChanges {

  /**
   * Default starting page for this component.
   * @private
   */
  private readonly initPage: number = 1;

  /**
   * The current displayed page number.
   */
  public currentPage: number = this.initPage;

  @Input('currentPage')
  public set CurrentPage(page: number) {
    this.currentPage = page || this.initPage;
  }

  /**
   * Total number of items.
   */
  public totalItems: number = 0;

  @Input('totalItems')
  public set TotalItems(total: number) {
    this.totalItems = total || 0;
  }

  /**
   * Max number of items in a page list.
   */
  public pageSize: number = 10;

  @Input('pageSize')
  public set PageSize(size: number) {
    this.pageSize = size || 10;
  }

  /**
   * Max number of pages displayed in the pagination.
   */
  public maxPages: number = 5;

  @Input('maxPages')
  public set MaxPages(max: number) {
    this.maxPages = max || 5;
  }

  /**
   * Pagination pager instance.
   */
  public pager: Pager;

  /**
   * Event Emitter when the page was changed.
   */
  @Output() public pageChange: EventEmitter<number> = new EventEmitter<number>();

  public ngOnInit(): void {
    this.pager = this.paginate(this.currentPage);
  }

  public ngOnChanges(changes: SimpleChanges): void {
    this.pager = this.paginate(this.currentPage);
  }

  public setPage(page: number): void {
    if (page < 1) {
      this.currentPage = 1;
    } else if (page > this.pager.totalPages) {
      this.currentPage = this.pager.totalPages;
    } else {
      this.currentPage = page;
    }
    this.pager = this.paginate(this.currentPage);
    this.pageChange.emit(this.currentPage);
  }

  /**
   * Generates a `Pager` object from a given page number.
   * @param currentPage - The current displayed page number.
   *                      Default is 1.
   */
  public paginate(currentPage: number = 1): Pager {

    const pageSize = this.pageSize;
    const maxPages = this.maxPages;
    const totalItems = this.totalItems;
    const totalPages = Math.ceil(this.totalItems / pageSize);

    if (currentPage < 1) {
      currentPage = 1;
    } else if (currentPage > totalPages) {
      currentPage = totalPages;
    }

    let startPage: number;
    let endPage: number;
    if (totalPages <= maxPages) {
      startPage = 1;
      endPage = totalPages;
    } else {
      const maxPagesBeforeCurrentPage = Math.floor(maxPages / 2);
      const maxPagesAfterCurrentPage = Math.ceil(maxPages / 2) - 1;
      if (currentPage <= maxPagesBeforeCurrentPage) {
        startPage = 1;
        endPage = maxPages;
      } else if (currentPage + maxPagesAfterCurrentPage >= totalPages) {
        startPage = totalPages - maxPages + 1;
        endPage = totalPages;
      } else {
        startPage = currentPage - maxPagesBeforeCurrentPage;
        endPage = currentPage + maxPagesAfterCurrentPage;
      }
    }

    const startIndex = (currentPage - 1) * pageSize;
    const endIndex = Math.min(startIndex + pageSize - 1, totalItems - 1);
    const pages = Array.from(Array((endPage + 1) - startPage).keys()).map(i => startPage + i);

    return { totalItems, currentPage, pageSize, totalPages, startPage, endPage, startIndex, endIndex, pages } as Pager;
  }

}
