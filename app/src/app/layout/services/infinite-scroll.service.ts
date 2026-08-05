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
* along with this program.  If not, see <https://www.gnu.org/licenses/>.
*/

import { Injectable } from '@angular/core';
import { CollectionParameters } from '../../services/models/api-parameter';

@Injectable({
  providedIn: 'root'
})
export class InfiniteScrollService {

  private apiCollection = new Map<string, CollectionParameters>();

  /**
   * Detecting scroll direction
   */
  private scrollTop: number = 0;
  private clientHeight: number = 0;
  private scrollHeight: number = 0;

  /**
   * Controls if end was reached
   *
   * @param event event which takes place in the DOM.
   * @param unique name of scrollable container
   */
  public bottomReached(event: Event, unique: string): boolean {
    this.scrollTop = (event.target as Element).scrollTop;
    this.clientHeight = (event.target as Element).clientHeight;
    this.scrollHeight = (event.target as Element).scrollHeight;

    return this.scrollUp(unique) && Math.round((this.scrollTop + this.clientHeight) - this.scrollHeight) === 0;
  }


  /**
   * Controls if end was reached
   *
   * @param page current page
   * @param limit fetch limit
   * @param sort by name
   * @param order desc or acs
   * @param unique name of scrollable container
   */
  public setCollectionParameters(page: number, limit: number, sort?: string, order?: number, unique?: string): void {
    const apiParams: CollectionParameters = { page, limit, sort, order, optional: {lastScroll: this.scrollTop} };
    this.apiCollection.set(unique, apiParams);
  }


  /**
   * Controls if end was reached
   *
   * @param unique name of scrollable container
   * @return boolean CollectionParameters Api Parameters
   */
  public getCollectionParameters(unique: string): CollectionParameters {
    return this.apiCollection.get(unique);
  }

  /**
   * Detecting scroll direction
   *
   * @param unique name of scrollable container
   * @return true when scrolling down otherwise false
   */
  private scrollUp(unique: string): boolean {
    return this.scrollTop > (this.apiCollection.get(unique).optional as any).lastScroll;
  }
}
