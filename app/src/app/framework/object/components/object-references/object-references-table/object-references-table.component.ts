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

import {Component, Input, OnDestroy, TemplateRef, ViewChild, ChangeDetectorRef} from '@angular/core';
import {BehaviorSubject, ReplaySubject} from 'rxjs';
import { ObjectService } from '../../../../services/object.service';
import { RenderResult } from '../../../../models/cmdb-render';
import { APIGetMultiResponse } from '../../../../../services/models/api-response';
import {Column, Sort, SortDirection, TableState, TableStatePayload} from '../../../../../layout/table/table.types';
import { CollectionParameters } from '../../../../../services/models/api-parameter';
import { takeUntil } from 'rxjs/operators';
import { DatePipe } from '@angular/common';
import { SupportedExporterExtension } from '../../../../../export/export-objects/model/supported-exporter-extension';
import { FileSaverService } from 'ngx-filesaver';
import { FileService } from '../../../../../export/export.service';
import {ActivatedRoute, Data, Router} from '@angular/router';
import {UserSetting} from '../../../../../management/user-settings/models/user-setting';
import {
  convertResourceURL,
  UserSettingsService
} from '../../../../../management/user-settings/services/user-settings.service';
import {UserSettingsDBService} from '../../../../../management/user-settings/services/user-settings-db.service';

@Component({
    selector: 'cmdb-object-references-table',
    templateUrl: './object-references-table.component.html',
    styleUrls: ['./object-references-table.component.scss'],
    standalone: false
})
export class ObjectReferencesTableComponent implements OnDestroy {

  /**
   * The Id of the table
   */
  public readonly id: string = 'object-referers-table';

  /**
   * Table Template: active column.
   */
  @ViewChild('activeTemplate', { static: true }) activeTemplate: TemplateRef<any>;

  /**
   * Table Template: Type name column.
   */
  @ViewChild('typeNameTemplate', { static: true }) typeNameTemplate: TemplateRef<any>;

  /**
   * Table Template: Link action column.
   */
  @ViewChild('actionTemplate', { static: true }) actionTemplate: TemplateRef<any>;

  /**
   * Table Template: reference column.
   */
  @ViewChild('referenceType', { static: true }) referenceType: TemplateRef<any>;


  /**
   * Table Template: export button column.
   */
  @ViewChild('exportButtonTemplate', { static: true }) exportButtonTemplate: TemplateRef<any>;

  /**
   * Global un-subscriber for http calls to the rest backend.
   */
  private subscriber: ReplaySubject<void> = new ReplaySubject<void>();

  /**
   * ID of the referenced object.
   */
  public publicID: number;

  /**
   * Filter parameter from table search
   */
  public filter: string;

  /**
   * ID setter of the referenced object.
   * @param id
   */
  @Input('publicID') public set PublicID(id: number) {
    this.publicID = id;
    this.setupTableColumns();
    this.initTable();
    this.loadObjectsFromAPI();
  }

  /**
   * Table columns definition.
   */
  public columns: Array<Column>;

  public refererObjects: Array<RenderResult> = [];
  public refererAPIResponse: APIGetMultiResponse<RenderResult>;
  public totalReferer: number = 0;

  /**
   * Referer selection.
   */
  public selectedObjects: Array<RenderResult> = [];
  public selectedObjectIDs: Array<number> = [];


  /**
   * Max number of objects per site.
   * @private
   */
  private readonly initLimit: number = 10;
  public limit: number = this.initLimit;

  /**
   * Begin with first page.
   */
  public readonly initPage: number = 1;
  public page: number = this.initPage;

  /**
   * Default sort filter.
   */
  public sort: Sort = { name: 'public_id', order: SortDirection.DESCENDING } as Sort;

  /**
   * Loading indicator.
   */
  public loading: boolean = false;

  /**
   * Possible export formats.
   */
  public formatList: Array<SupportedExporterExtension> = [];

  public tableStateSubject: BehaviorSubject<TableState> = new BehaviorSubject<TableState>(undefined);

  public tableStates: Array<TableState> = [];

  public get tableState(): TableState {
    return this.tableStateSubject.getValue() as TableState;
  }


  constructor(private objectService: ObjectService, private datePipe: DatePipe,
              private fileSaverService: FileSaverService, private fileService: FileService,
              private route: ActivatedRoute, private router: Router,
              private userSettingsService: UserSettingsService<UserSetting, TableStatePayload>,
              private indexDB: UserSettingsDBService<UserSetting, TableStatePayload>,
              private changesRef: ChangeDetectorRef) {
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
        const userSetting = userSettingsService.createUserSetting<TableStatePayload>(resource, [statePayload]);
        this.indexDB.addSetting(userSetting);
      }
    });
    this.fileService.callFileFormatRoute().subscribe(data => {
      this.formatList = data;
    });
  }

  public setupTableColumns(): void {
    this.columns = [
      {
        display: 'Active',
        name: 'active',
        data: 'object_information.active',
        sortable: true,
        template: this.activeTemplate,
        cssClasses: ['text-center'],
        style: { width: '6rem' }
      },
      {
        display: 'Public ID',
        name: 'public_id',
        data: 'object_information.object_id',
        sortable: true
      },
      {
        display: 'Reference Type',
        name: 'reference_type',
        sortable: false,
        searchable: false,
        template: this.referenceType
      },
      {
        display: 'Type',
        name: 'type_id',
        data: 'type_information.type_name',
        sortable: true,
        template: this.typeNameTemplate,
      },
      {
        display: 'Summary',
        name: 'summary',
        data: 'summary_line',
        sortable: false
      },
      {
        display: 'Creation Time',
        name: 'creation_time',
        data: 'object_information.creation_time',
        sortable: true,
        searchable: false,
        render(data: any) {
          const date = new Date(data);
          return new DatePipe('en-US').transform(date, 'dd/MM/yyyy - hh:mm:ss').toString();
        }
      },
      {
        display: 'Actions',
        name: 'actions',
        data: 'object_information.object_id',
        template: this.actionTemplate,
        sortable: false,
        fixed: true,
        cssClasses: ['text-center'],
        cellClasses: ['actions-buttons'],
        style: { width: '6rem' }
      },
    ] as Array<Column>;
  }

  /**
   * Initialize table state
   */
  private initTable() {
    if (this.tableState) {
      this.sort = this.tableState.sort;
      this.limit = this.tableState.pageSize;
      this.page = this.tableState.page;
    }
  }

  /**
   * Load/reload objects from the api.
   * @private
   */
  private loadObjectsFromAPI(): void {
    this.loading = true;
    const filter = this.filterBuilder(this.columns);
    const params: CollectionParameters = {
      filter, limit: this.limit,
      sort: this.sort.name, order: this.sort.order, page: this.page
    };

    this.objectService.getObjectReferences(this.publicID, params).pipe(takeUntil(this.subscriber)).subscribe(
      (apiResponse: APIGetMultiResponse<RenderResult>) => {
        this.refererAPIResponse = apiResponse;
        this.refererObjects = apiResponse.results as Array<RenderResult>;
        this.totalReferer = apiResponse.total;
        this.loading = false;
        this.changesRef.markForCheck();
      });
  }

  /**
   * DB Query / Filter Builder
   * Creates a database query using the passed parameters.
   *
   * @param columns {@link Array<Column>} are taken into account in the query.
   * @return query {@link: any[]}
   */
  private filterBuilder(columns: Array<Column>) {
    let query;
    const or = [];
    if (this.filter) {
      query = [];
      for (const column of columns) {
        const regex: any = {};
        regex[column.name] = {
          $regex: String(this.filter),
          $options: 'ismx'
        };
        or.push(regex);
      }
      // Search into reference fields
      query.push(
        {
          $lookup: {
            from: 'framework.objects',
            localField: 'fields.value',
            foreignField: 'public_id',
            as: 'data'
          }
        });

      query.push({ $project: {
          _id: 1,
          public_id: 1,
          type_id: 1,
          active: 1,
          author_id: 1,
          creation_time: 1,
          last_edit_time: 1,
          fields: 1,
          simple: {
            $reduce: {
              input: '$data.fields',
              initialValue: [],
              in: { $setUnion: ['$$value', '$$this'] }
            }
          }
        } });

      query.push({
        $group: {
          _id: '$_id',
          public_id : { $first: '$public_id' },
          type_id: { $first: '$type_id' },
          active: { $first: '$active' },
          author_id: { $first: '$author_id' },
          creation_time: { $first: '$creation_time' },
          last_edit_time: { $first: '$last_edit_time' },
          fields : { $first: '$fields' },
          simple: { $first: '$simple' },
        }
      });

      query.push({ $project:
            {
              _id: '$_id',
              public_id: 1,
              type_id: 1,
              active: 1,
              author_id: 1,
              creation_time: 1,
              last_edit_time: 1,
              fields: 1,
              references : { $setUnion: ['$fields', '$simple'] },
            }
        }
      );
      // Search for creation_time
      query.push(
        { $addFields: {
            creationString: { $dateToString: { format: '%Y-%m-%dT%H:%M:%S.%LZ', date: '$creation_time' } }
          }},
      );
      // Search for last_edit_time
      query.push(
        { $addFields: {
            editString: { $dateToString: { format: '%Y-%m-%dT%H:%M:%S.%LZ', date: '$last_edit_time' } }
          }},
      );
      // Search date in field values
      query.push(
        { $addFields: {
            references: {
              $map: {
                input: '$references',
                as: 'new_fields',
                in: {
                  $cond: [
                    { $eq: [{ $type: '$$new_fields.value' }, 'date'] },
                    { name: '$$new_fields.name', value: {
                      $dateToString: { format: '%Y-%m-%dT%H:%M:%S.%LZ', date: '$$new_fields.value' } }
                    },
                    { name: '$$new_fields.name', value: '$$new_fields.value'}
                  ]
                }
              }
            }
          }
        },
      );
      // Nasty public id quick hack
      query.push({
        $addFields: {
          public_id: { $toString: '$public_id' }
        }
      });
      or.push({
        public_id: {
          $elemMatch: {
            value: {
              $regex: String(this.filter),
              $options: 'ism'
            }
          }
        }
      });
      // Date string search
      or.push( { creationString: { $regex: String(this.filter), $options: 'ims' } } );
      or.push( { editString: { $regex: String(this.filter), $options: 'ims' } } );
      // Search Fields
      or.push({
        references: {
          $elemMatch: {
            value: {
              $regex: String(this.filter),
              $options: 'ism'
            }
          }
        }
      });
      query.push({ $match: { $or: or } });
    }
    return query;
  }

  /**
   * On table search change.
   * Reload all objects.
   *
   * @param search
   */
  public onSearchChange(search: any): void {
    this.page = this.initPage;
    if (search) {
      this.filter = search;
    } else {
      this.filter = undefined;
    }
    this.loadObjectsFromAPI();
  }

  /**
   * Select a state.
   *
   * @param state
   */
  public onStateSelect(state: TableState): void {
    this.tableStateSubject.next(state);
    this.page = this.tableState.page;
    this.limit = this.tableState.pageSize;
    this.sort = this.tableState.sort;
    this.loadObjectsFromAPI();
  }

  public onStateReset(): void {
    this.sort = { name: 'public_id', order: SortDirection.DESCENDING } as Sort;
    this.limit = this.initLimit;
    this.page = this.initPage;
    this.loadObjectsFromAPI();
  }


  /**
   * On table sort change.
   * Reload all objects.
   *
   * @param sort
   */
  public onSortChange(sort: Sort): void {
    this.sort = sort;
    this.loadObjectsFromAPI();
  }

  /**
   * On table page change.
   * Reload all objects.
   *
   * @param page
   */
  public onPageChange(page: number) {
    this.page = page;
    this.loadObjectsFromAPI();
  }

  /**
   * On table page size change.
   * Reload all objects.
   *
   * @param limit
   */
  public onPageSizeChange(limit: number): void {
    this.limit = limit;
    this.loadObjectsFromAPI();
  }

  /**
   * On table selection change.
   * Map selected items by the object id
   *
   * @param selectedItems
   */
  public onSelectedChange(selectedItems: Array<RenderResult>): void {
    this.selectedObjects = selectedItems;
    this.selectedObjectIDs = selectedItems.map(t => t.object_information.object_id);
  }

  /**
   * Exports the referenceList as zip
   *
   * @param see the filetype to be zipped
   */
  public exportingFiles(see: SupportedExporterExtension) {
    const filter = {public_id: {$in: this.selectedObjectIDs}};
    const optional = {classname: see.extension, zip: true};
    const exportAPI: CollectionParameters = {filter, optional, order: this.sort.order, sort: this.sort.name};
    if (this.selectedObjects.length !== 0) {
      this.fileService.callExportRoute(exportAPI)
        .subscribe(res => this.downLoadFile(res));
    }
  }

  /**
   * Downloads file
   * @param data the file data to be downloaded
   */
  public downLoadFile(data: any) {
    const timestamp = this.datePipe.transform(new Date(), 'MM_dd_yyyy_hh_mm_ss');
    this.fileSaverService.save(data.body, timestamp + '.' + 'zip');
  }

  /**
   * Unsubscribe all on component destroy.
   */
  public ngOnDestroy(): void {
    this.subscriber?.next();
    this.subscriber?.complete();
  }
}
