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

import { Component, inject, Input, OnDestroy, OnInit } from '@angular/core';
import { Column, Sort, SortDirection } from '../../../../layout/table/table.types';
import { User } from '../../../models/user';
import { ReplaySubject } from 'rxjs';
import { CollectionParameters } from '../../../../services/models/api-parameter';
import { takeUntil } from 'rxjs/operators';
import { APIGetMultiResponse } from '../../../../services/models/api-response';
import { UserService } from '../../../services/user.service';

@Component({
    selector: 'cmdb-user-table-list',
    templateUrl: './user-table-list.component.html',
    styleUrls: ['./user-table-list.component.scss'],
    standalone: false
})
export class UserTableListComponent implements OnInit, OnDestroy {

  /**
   * Component un-subscriber.
   * @private
   */
  private subscriber: ReplaySubject<void> = new ReplaySubject<void>();

  /**
   * Collection params
   */
  public params: CollectionParameters = { filter: undefined, limit: 10, sort: 'public_id', order: 1, page: 1 };
  public columns: Array<Column> = [];
  public totalUsers: number;

  @Input('filter')
  public set Filter(filter: any) {
    this.params.filter = filter;
  }

  /**
   * Table loading?
   */
  public loading: boolean = false;

  /**
   * Default sort parameter
   */
  public sort: Sort = { name: 'public_id', order: SortDirection.DESCENDING } as Sort;

  /**
   * Users
   */
  public users: Array<User> = [];

  private readonly userService = inject(UserService);

  public ngOnInit(): void {
    this.columns = [
      {
        display: 'Public ID',
        name: 'public_id',
        data: 'public_id',
        searchable: true,
        sortable: true
      },
      {
        display: 'Username',
        name: 'user_name',
        data: 'user_name',
        searchable: true,
        sortable: true
      },
      {
        display: 'Firstname',
        name: 'first_name',
        data: 'first_name',
        searchable: true,
        sortable: true
      },
      {
        display: 'Lastname',
        name: 'last_name',
        data: 'last_name',
        searchable: true,
        sortable: true
      }
    ] as Array<Column>;
    this.loadUsersFromApi();
  }

  private loadUsersFromApi(): void {
    this.loading = true;
    this.userService.getUsers(this.params).pipe(takeUntil(this.subscriber)).subscribe((response: APIGetMultiResponse<User>) => {
      this.users = response.results as Array<User>;
      this.totalUsers = response.total;
      this.loading = false;
    });
  }

  /**
   * On table page change.
   * Reload all users.
   *
   * @param page
   */
  public onPageChange(page: number) {
    this.params.page = page;
    this.loadUsersFromApi();
  }

  /**
   * On table page size change.
   * Reload all users.
   *
   * @param limit
   */
  public onPageSizeChange(limit: number): void {
    this.params.limit = limit;
    this.loadUsersFromApi();
  }

  /**
   * On table sort change.
   * Reload all users.
   *
   * @param sort
   */
  public onSortChange(sort: Sort): void {
    this.sort = sort;
    this.params.sort = sort.name;
    this.params.order = sort.order;
    this.loadUsersFromApi();
  }

  /**
   * On destroying the group component,
   * auto unsubscribe the api subscriptions.
   */
  public ngOnDestroy(): void {
    this.subscriber?.next();
    this.subscriber?.complete();
  }

}
