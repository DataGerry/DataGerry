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

import { Component, inject, Input, OnDestroy, OnInit, TemplateRef, ViewChild } from '@angular/core';
import { ReplaySubject } from 'rxjs';
import { CollectionParameters } from '../../../../services/models/api-parameter';
import { Column, Sort, SortDirection } from '../../../../layout/table/table.types';
import { takeUntil } from 'rxjs/operators';
import { APIGetMultiResponse } from '../../../../services/models/api-response';
import { GroupService } from '../../../services/group.service';
import { Group } from 'src/app/management/models/group';

@Component({
    selector: 'cmdb-group-table-list',
    templateUrl: './group-table-list.component.html',
    styleUrls: ['./group-table-list.component.scss'],
    standalone: false
})
export class GroupTableListComponent implements OnInit, OnDestroy {

  /**
   * Component un-subscriber.
   * @private
   */
  private subscriber: ReplaySubject<void> = new ReplaySubject<void>();

  /**
   * Table Template: Group users column.
   */
  @ViewChild('usersTemplate', { static: true }) public usersTemplate: TemplateRef<any>;

  /**
   * Collection params
   */
  public params: CollectionParameters = { filter: undefined, limit: 10, sort: 'public_id', order: 1, page: 1 };
  public columns: Array<Column> = [];
  public totalGroups: number;

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
   * Groups
   */
  public groups: Array<Group> = [];

  private readonly groupService = inject(GroupService);

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
        display: 'Name',
        name: 'name',
        data: 'name',
        searchable: true,
        sortable: true
      },
      {
        display: 'Label',
        name: 'label',
        data: 'label',
        searchable: true,
        sortable: true
      },
      {
        display: 'Users',
        name: 'users',
        data: 'public_id',
        searchable: false,
        sortable: false,
        fixed: true,
        template: this.usersTemplate,
        cssClasses: ['text-center']
      }
    ] as Array<Column>;
    this.loadGroupsFromApi();
  }

  private loadGroupsFromApi(): void {
    this.loading = true;
    this.groupService.getGroups(this.params).pipe(takeUntil(this.subscriber)).subscribe((response: APIGetMultiResponse<Group>) => {
      this.groups = response.results as Array<Group>;
      this.totalGroups = response.total;
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
    this.loadGroupsFromApi();
  }

  /**
   * On table page size change.
   * Reload all users.
   *
   * @param limit
   */
  public onPageSizeChange(limit: number): void {
    this.params.limit = limit;
    this.loadGroupsFromApi();
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
    this.loadGroupsFromApi();
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
