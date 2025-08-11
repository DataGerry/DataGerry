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

import { Component, Input, OnInit, TemplateRef, ViewChild } from '@angular/core';
import { CmdbLog } from '../../../models/cmdb-log';
import { Column, Sort, SortDirection } from '../../../../layout/table/table.types';
import { APIGetMultiResponse } from '../../../../services/models/api-response';
import { CollectionParameters } from '../../../../services/models/api-parameter';
import { LogService } from 'src/app/framework/services/log.service';

@Component({
    selector: 'cmdb-object-log-list',
    templateUrl: './object-log-list.component.html',
    styleUrls: ['./object-log-list.component.scss'],
    standalone: false
})
export class ObjectLogListComponent implements OnInit {

  private id: number;

  @Input()
  set publicID(publicID: number) {
    this.id = publicID;
    if (this.id !== undefined && this.id !== null) {
      this.loadLogList();
    }
  }

  get publicID(): number {
    return this.id;
  }

  @ViewChild('dateTemplate', {static: true}) dateTemplate: TemplateRef<any>;

  @ViewChild('linkTemplate', {static: true}) linkTemplate: TemplateRef<any>;

  @ViewChild('dataTemplate', {static: true}) dataTemplate: TemplateRef<any>;

  @ViewChild('changeTemplate', {static: true}) changeTemplate: TemplateRef<any>;

  @ViewChild('userTemplate', {static: true}) userTemplate: TemplateRef<any>;

  public filter: string;

  public logList: CmdbLog[] = [];

  public columns: Array<Column>;

  public sort: Sort = { name: 'log_time', order: SortDirection.DESCENDING } as Sort;

  private readonly initLimit: number = 10;
  public limit: number = this.initLimit;

  public readonly initPage: number = 1;
  public page: number = this.initPage;

  public total: number = 0;
  public loading: boolean = false;

  public apiParameters: CollectionParameters;

  constructor(private logService: LogService) {
  }

  private loadLogList() {
    this.apiParameters = { filter: this.filterBuilder(),
      limit: this.limit, sort: this.sort.name, order: this.sort.order, page: this.page};
    this.logService.getLogsByObject(this.publicID, this.apiParameters)
      .subscribe((apiResponse: APIGetMultiResponse<CmdbLog>) => {
      this.logList = apiResponse.results;
      this.total = apiResponse.total;
    });
  }

  private resetCollectionParameters(): void {
    this.apiParameters = { limit: 10, sort: 'date', order: -1, page: 1};
  }

  public filterBuilder(): any {
    const query = [];
    if (this.filter) {
      const searchableColumns = this.columns.filter(c => c.searchable);
      const or = [];
      // Searchable Columns
      for (const column of searchableColumns) {
        const regex: any = {};
        regex[column.name] = {
          $regex: String(this.filter),
          $options: 'ismx'
        };
        or.push(regex);
      }
      query.push({
        $addFields: {
          public_id: { $toString: '$public_id' }
        }
      });
      query.push({ $match: { $and: [{log_type: 'CmdbObjectLog', object_id: this.publicID}, {$or: or}]}});
    } else {
      query.push({$match: {log_type: 'CmdbObjectLog', object_id: this.publicID}});
    }
    return query;
  }

  public ngOnInit(): void {
    this.resetCollectionParameters();
    this.setColumns();
  }

  private setColumns(): void {
    const columns = [];
    columns.push(
      {
        display: 'Log Time',
        name: 'log_time',
        data: 'log_time',
        sortable: true,
        cssClasses: ['text-center'],
        style: { 'white-space': 'nowrap' },
        template: this.dateTemplate,
        searchable: false,
      } as Column
    );

    columns.push({
      display: 'Log ID',
      name: 'public_id',
      data: 'public_id',
      sortable: true,
      searchable: true,
      fixed: true,
      template: this.dataTemplate,
      style: { 'white-space': 'nowrap' },
    } as unknown as Column);

    columns.push({
      display: 'Action',
      name: 'action_name',
      data: 'action_name',
      sortable: true,
      searchable: false,
      fixed: true,
      cssClasses: ['text-center'],
      style: { width: '6em' }
    } as unknown as Column);

    columns.push({
      display: 'Changes',
      name: 'changes',
      sortable: true,
      searchable: false,
      fixed: true,
      template: this.changeTemplate,
    } as unknown as Column);

    columns.push({
      display: 'Comment',
      name: 'comment',
      data: 'comment',
      sortable: true,
      searchable: false,
      fixed: true,
      cssClasses: ['text-center'],
      style: { width: '6em' }
    } as unknown as Column);

    columns.push({
      display: 'Author',
      data: 'author_name',
      name: 'author_name',
      sortable: true,
      searchable: false,
      fixed: true,
      template: this.userTemplate,
      cssClasses: ['text-center'],
      style: { width: '6em' }
    } as unknown as Column);

    columns.push({
      display: 'Version',
      name: 'version',
      data: 'version',
      sortable: true,
      searchable: true,
      fixed: true,
      cssClasses: ['text-center'],
      style: { width: '6em' }
    } as unknown as Column);

    columns.push({
      display: 'Links',
      name: 'links',
      data: 'public_id',
      sortable: true,
      searchable: false,
      fixed: true,
      template: this.linkTemplate,
      cssClasses: ['text-center'],
      style: { width: '6em' }
    } as unknown as Column);

    this.columns = columns;
  }
  public onPageChange(page: number) {
    this.page = page;
    this.loadLogList();
  }

  public onPageSizeChange(limit: number): void {
    this.limit = limit;
    this.loadLogList();
  }

  public onSortChange(sort: Sort): void {
    this.sort = sort;
    this.loadLogList();
  }

  public onSearchChange(search: any): void {
    if (search) {
      this.filter = search;
    } else {
      this.filter = undefined;
    }
    this.loadLogList();
  }

}
