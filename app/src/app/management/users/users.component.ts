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

import { Component, OnDestroy, OnInit, TemplateRef, ViewChild } from '@angular/core';
import { User } from '../models/user';
import { APIGetMultiResponse } from '../../services/models/api-response';
import { UserService } from '../services/user.service';
import { BehaviorSubject, ReplaySubject } from 'rxjs';
import { CollectionParameters } from '../../services/models/api-parameter';
import { takeUntil } from 'rxjs/operators';
import { Column, Sort, SortDirection, TableState, TableStatePayload } from '../../layout/table/table.types';
import { NgbModal, NgbModalRef } from '@ng-bootstrap/ng-bootstrap';
import { UsersPasswdModalComponent } from './modals/users-passwd-modal/users-passwd-modal.component';
import { GroupService } from '../services/group.service';
import { Group } from '../models/group';
import { ActivatedRoute, Data, Router } from '@angular/router';
import { UserSetting } from '../user-settings/models/user-setting';
import { convertResourceURL, UserSettingsService } from '../user-settings/services/user-settings.service';
import { UserSettingsDBService } from '../user-settings/services/user-settings-db.service';
import { environment } from 'src/environments/environment';
import { ToastService } from 'src/app/layout/toast/toast.service';

@Component({
    selector: 'cmdb-users',
    templateUrl: './users.component.html',
    styleUrls: ['./users.component.scss'],
    standalone: false
})
export class UsersComponent implements OnInit, OnDestroy {

  isCloudMode = environment.cloudMode;

  /**
   * Id for the user Table
   */
  public readonly id: string = 'user-list-table';

  /**
   * Component un-subscriber.
   * @private
   */
  private subscriber: ReplaySubject<void> = new ReplaySubject<void>();

  /**
   * Component title h1.
   */
  public readonly title: string = 'User';

  /**
   * Title small.
   */
  public readonly description: string = 'Management';

  /**
   * Table Template: User add button.
   */
  @ViewChild('addButtonTemplate', { static: true }) public buttonTemplate: TemplateRef<any>;

  /**
   * Table Template: User group column.
   */
  @ViewChild('groupTemplate', { static: true }) public groupTemplate: TemplateRef<any>;

  /**
   * Table Template: User actions column.
   */
  @ViewChild('actionsTemplate', { static: true }) public actionsTemplate: TemplateRef<any>;

  /**
   * Table Template: User date column.
   */
  @ViewChild('dateTemplate', { static: true }) public dateTemplate: TemplateRef<any>;

  /**
   * Password modal
   */
  private modalRef: NgbModalRef;

  /**
   * Users
   */
  public users: Array<User> = [];

  /**
   * Groups
   */
  public groups: Array<Group> = [];

  /**
   * Is the group currently loading
   */
  public groupLoadingStack: Array<number> = [];

  /**
   * Backend api response
   */
  private apiUsersResponse: APIGetMultiResponse<User>;

  /**
   * Table loading?
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
  public totalUsers: number;

  public tableStateSubject: BehaviorSubject<TableState> = new BehaviorSubject<TableState>(undefined);

  public tableStates: Array<TableState> = [];

  public get tableState(): TableState {
    return this.tableStateSubject.getValue() as TableState;
  }

  constructor(private userService: UserService, private groupService: GroupService, private modalService: NgbModal,
    private router: Router, private route: ActivatedRoute,
    private userSettingsService: UserSettingsService<UserSetting, TableStatePayload>,
    private indexDB: UserSettingsDBService<UserSetting, TableStatePayload>, private toastService: ToastService) {
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

  public getGroupByID(publicID: number): Group {
    return this.groups.find(group => group.public_id === publicID);
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
      },
      {
        display: 'Email',
        name: 'email',
        data: 'email',
        searchable: true,
        sortable: true
      },
      {
        display: 'Registered since',
        name: 'registration_time',
        data: 'registration_time',
        sortable: true,
        searchable: false,
        template: this.dateTemplate,
      },
      {
        display: 'Group',
        name: 'group_id',
        data: 'group_id',
        searchable: false,
        sortable: true,
        template: this.groupTemplate,
        render(data: any) {
          return +data;
        }
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
    this.loadUsersFromApi();
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
   * Load users from the API.
   * Updates the user list, total count, and loading state.
   */
  private loadUsersFromApi(): void {
    this.loading = true;
    this.userService.getUsers(this.params)
      .pipe(takeUntil(this.subscriber))
      .subscribe({
        next: (response: APIGetMultiResponse<User>) => {
          this.users = response.results as Array<User>;
          this.totalUsers = response.total;
          this.apiUsersResponse = response;
          this.loading = false;
        },
        error: (err) => {
          this.toastService.error(err?.error?.message);
          this.loading = false;
        }
      });
  }
  

  /**
   * Open password change modal.
   * Passes the selected user to the modal component.
   *
   * @param user The user whose password should be changed
   */
  public onPasswordChange(user: User): void {
    this.modalRef = this.modalService.open(UsersPasswdModalComponent, { size: 'lg' });
    this.modalRef.componentInstance.user = user;
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
    this.loadUsersFromApi();
  }


  /**
   * On State Select.
   * Updates table settings according to the given table state
   * @param state
   */
  public onStateSelect(state: TableState) {
    this.params.page = this.tableState.page;
    this.params.limit = this.tableState.pageSize;
    this.sort = this.tableState.sort;
    this.params.sort = this.sort.name;
    this.params.order = this.sort.order;
    for (const col of this.columns) {
      col.hidden = !this.tableState.visibleColumns.includes(col.name);
    }
    this.tableStateSubject.next(state);
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
   * On table search change.
   * Reload all users.
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


  public ngOnDestroy(): void {
    if (this.modalRef) {
      this.modalRef.close();
    }
    this.subscriber?.next();
    this.subscriber?.complete();
  }

}
