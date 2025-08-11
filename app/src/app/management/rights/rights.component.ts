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
import { Right, SecurityLevel } from '../models/right';
import { ActivatedRoute } from '@angular/router';
import { ReplaySubject } from 'rxjs';
import { Column, Sort } from '../../layout/table/table.types';
import { finalize, takeUntil } from 'rxjs/operators';
import { APIGetMultiResponse } from '../../services/models/api-response';
import { RightService } from '../services/right.service';
import { CollectionParameters } from '../../services/models/api-parameter';
import { LoaderService } from 'src/app/core/services/loader.service';

@Component({
    selector: 'cmdb-rights',
    templateUrl: './rights.component.html',
    styleUrls: ['./rights.component.scss'],
    standalone: false
})
export class RightsComponent implements OnInit, OnDestroy {

  /**
   * Component un-subscriber.
   * @private
   */
  private subscriber: ReplaySubject<void> = new ReplaySubject<void>();

  /**
   * Component title h1.
   */
  public readonly title: string = 'Right';

  /**
   * Title small.
   */
  public readonly description: string = 'Management';

  /**
   * List of all rights, loaded from backend.
   */
  public rights: Array<Right> = [];

  /**
   * Defined security levels
   */
  public securityLevels: SecurityLevel;

  /**
   * Table columns.
   */
  public columns: Array<Column> = [];

  /**
   * Collection params for api call.
   * @private
   */
  private params: CollectionParameters = { filter: undefined, limit: 0, sort: 'name', order: 1, page: 1 };

  /**
   * Table Template: level column.
   */
  @ViewChild('levelTemplate', { static: true }) public levelTemplate: TemplateRef<any>;

  /**
   * Table Template: groups with rights column.
   */
  @ViewChild('groupsRightTemplate', { static: true }) public groupsRightTemplate: TemplateRef<any>;

  public isLoading$ = this.loaderService.isLoading$;


  constructor(
    private route: ActivatedRoute, 
    private rightService: RightService,
    private loaderService: LoaderService
  ) {
    this.rights = this.route.snapshot.data.rights as Array<Right>;
  }

  public ngOnInit(): void {
    this.columns = [
      {
        display: 'Name',
        name: 'name',
        data: 'name',
        sortable: true
      },
      {
        display: 'Label',
        name: 'label',
        data: 'label',
        sortable: true
      },
      {
        display: 'Description',
        name: 'description',
        data: 'description',
        sortable: true
      },
      {
        display: 'Level',
        name: 'level',
        data: 'level',
        sortable: true,
        render(data: any) {
          if (!data) {
            return '0';
          }
          return data;
        },
        template: this.levelTemplate
      },
      {
        display: 'Groups',
        name: 'groups',
        data: 'name',
        sortable: false,
        template: this.groupsRightTemplate
      }
    ] as Array<Column>;
  }

  /**
   * Loads the rights from the api based on the params.
   */
  public loadRightsFromAPI() {
    this.loaderService.show()
    this.rightService.getRights(this.params).pipe(takeUntil(this.subscriber), finalize(() => this.loaderService.hide()))
      .subscribe((response: APIGetMultiResponse<Right>) => {
        this.rights = response.results as Array<Right>;
      });
  }

  /**
   * On table sort change.
   * Reload all rights.
   *
   * @param sort
   */
  public onSortChange(sort: Sort): void {
    this.params.sort = sort.name;
    this.params.order = sort.order;
    this.loadRightsFromAPI();
  }

  /**
   * Un-subscribe on component close.
   */
  public ngOnDestroy(): void {
    this.subscriber?.next();
    this.subscriber?.complete();
  }

}
