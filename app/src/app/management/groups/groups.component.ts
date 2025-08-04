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

import { Component, OnDestroy, OnInit, TemplateRef, ViewChild } from '@angular/core';
import { GroupService } from '../services/group.service';
import { BehaviorSubject, ReplaySubject } from 'rxjs';
import { Group } from '../models/group';
import { APIGetMultiResponse } from '../../services/models/api-response';
import { CollectionParameters } from '../../services/models/api-parameter';
import { takeUntil } from 'rxjs/operators';
import { Column, Sort, SortDirection, TableState, TableStatePayload } from '../../layout/table/table.types';
import { ActivatedRoute, Data, Router } from '@angular/router';
import { convertResourceURL, UserSettingsService } from '../user-settings/services/user-settings.service';
import { UserSetting } from '../user-settings/models/user-setting';
import { UserSettingsDBService } from '../user-settings/services/user-settings-db.service';
import { ToastService } from 'src/app/layout/toast/toast.service';

@Component({
  selector: 'cmdb-groups',
  templateUrl: './groups.component.html',
  styleUrls: ['./groups.component.scss']
})
export class GroupsComponent implements OnInit, OnDestroy {

  /**
   * The id of the table
   */
  public readonly id: string = 'group-list-table';

  /**
   * Component title h1.
   */
  public readonly title: string = 'Group';

  /**
   * Title small.
   */
  public readonly description: string = 'Management';

  /**
   * Subscriber replay for auto unsubscribe.
   */
  private subscriber: ReplaySubject<void> = new ReplaySubject<void>();

  /**
   * Table Template: Group add button.
   */
  @ViewChild('addButtonTemplate', { static: true }) public buttonTemplate: TemplateRef<any>;

  /**
   * Table Template: Group users column.
   */
  @ViewChild('usersTemplate', { static: true }) public usersTemplate: TemplateRef<any>;

  /**
   * Table Template: Group actions column.
   */
  @ViewChild('actionsTemplate', { static: true }) public actionsTemplate: TemplateRef<any>;

  /**
   * List of current loaded groups.
   */
  public groups: Array<Group> = [];

  /**
   * Backend http call response for user groups.
   */
  private groupAPIResponse: APIGetMultiResponse<Group>;

  /**
   * Table loading.
   */
  public loading: boolean = false;

  /**
   * Default sort parameter
   */
  public sort: Sort = { name: 'public_id', order: SortDirection.DESCENDING } as Sort;

  /**
   * Collection params
   */
  public params: CollectionParameters = { filter: undefined, limit: 10, sort: 'public_id', order: 1, page: 1 };
  public columns: Array<Column> = [];
  public totalGroups: number;

  public tableStateSubject: BehaviorSubject<TableState> = new BehaviorSubject<TableState>(undefined);

  public tableStates: Array<TableState> = [];

  public get tableState(): TableState {
    return this.tableStateSubject.getValue() as TableState;
  }

  constructor(private groupService: GroupService, private router: Router, private route: ActivatedRoute,
    private userSettingsService: UserSettingsService<UserSetting, TableStatePayload>,
    private indexDB: UserSettingsDBService<UserSetting, TableStatePayload>,
    private toastSerive: ToastService) {
    this.route.data.pipe(takeUntil(this.subscriber)).subscribe((data: Data) => {
      if (data.userSetting) {
        const userSettingPayloads = (data.userSetting as UserSetting<TableStatePayload>).payloads
          .find(payloads => payloads.id === this.id);
        this.tableStates = userSettingPayloads.tableStates;
        this.tableStateSubject.next(userSettingPayloads.currentState);
      } else {
        this.tableStates = [];
        this.tableStateSubject.next(undefined);

        const statePayload: TableStatePayload = new TableStatePayload(this.id, []);
        const resource: string = convertResourceURL(this.router.url.toString());
        const userSetting = this.userSettingsService.createUserSetting<TableStatePayload>(resource, [statePayload]);
        this.indexDB.addSetting(userSetting);
      }
    });
  }

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
      },
      {
        display: 'Actions',
        name: 'actions',
        searchable: false,
        sortable: false,
        fixed: true,
        template: this.actionsTemplate,
        cssClasses: ['text-center'],
        cellClasses: ['actions-buttons']
      }
    ] as Array<Column>;
    this.initTable();
    this.loadGroupsFromApi();
  }

  private initTable() {
    if (this.tableState) {
      this.sort = this.tableState.sort;
      this.params.sort = this.sort.name;
      this.params.order = this.sort.order;
      this.params.page = this.tableState.page;
      this.params.limit = this.tableState.pageSize;
    }
  }

  /**
   * Load the groups from the api.
   * @private
   */
  private loadGroupsFromApi(): void {
    this.loading = true;
    this.groupService.getGroups(this.params).pipe(takeUntil(this.subscriber))
      .subscribe({
        next: (response: APIGetMultiResponse<Group>) => {
          this.groups = response.results as Array<Group>;
          this.totalGroups = response.total;
          this.groupAPIResponse = response;
          this.loading = false;
        }
        ,
        error: (error) => {
          this.toastSerive.error(error?.error?.message);
        }
      }
      );
  }

  /**
   * On table page change.
   * Reload all groups.
   *
   * @param page
   */
  public onPageChange(page: number) {
    this.params.page = page;
    this.loadGroupsFromApi();
  }

  /**
   * On table page size change.
   * Reload all groups.
   *
   * @param limit
   */
  public onPageSizeChange(limit: number): void {
    this.params.limit = limit;
    this.loadGroupsFromApi();
  }

  /**
   * On table State change.
   * Update state.
   */
  public onStateChange(state: TableState): void {
    this.tableStateSubject.next(state);
  }

  /**
   * On table state reset.
   * Reset State.
   */
  public onStateReset(): void {
    this.params.page = this.tableState.page;
    this.params.limit = this.tableState.pageSize;
    this.sort = { name: 'public_id', order: SortDirection.DESCENDING } as Sort;
    this.params.sort = this.sort.name;
    this.params.order = this.sort.order;
    this.tableStateSubject.next(undefined);
    this.loadGroupsFromApi();
  }

  /**
   * On State Select.
   * Updates table settings according to the given table state
   * @param state
   */
  public onStateSelect(state: TableState) {
    this.tableStateSubject.next(state);
    this.params.page = this.tableState.page;
    this.params.limit = this.tableState.pageSize;
    this.sort = this.tableState.sort;
    this.params.sort = this.sort.name;
    this.params.order = this.sort.order;
    for (const col of this.columns) {
      col.hidden = !this.tableState.visibleColumns.includes(col.name);
    }
    this.tableStateSubject.next(state);
    this.loadGroupsFromApi();
  }

  /**
   * On table search change.
   * Reload all groups.
   *
   * @param search
   */
  public onSearchChange(search: any): void {
    if (search) {
      let query;
      query = [];
      const or = [];
      const searchableColumns = this.columns.filter(c => c.searchable);
      // Searchable Columns
      for (const column of searchableColumns) {
        const regex: any = {};
        regex[column.name] = {
          $regex: String(search),
          $options: 'ismx'
        };
        or.push(regex);
      }
      query.push({
        $addFields: {
          public_id: { $toString: '$public_id' }
        }
      });
      or.push({
        public_id: {
          $elemMatch: {
            value: {
              $regex: String(search),
              $options: 'ismx'
            }
          }
        }
      });
      query.push({ $match: { $or: or } });
      this.params.filter = query;
    } else {
      this.params.filter = undefined;
    }
    this.loadGroupsFromApi();
  }

  /**
   * On table sort change.
   * Reload all groups.
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
