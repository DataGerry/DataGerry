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
import { ReplaySubject, Subject } from 'rxjs';
import { ObjectService } from '../services/object.service';
import { CmdbObject } from '../models/cmdb-object';
import { RenderResult } from '../models/cmdb-render';
import { APIGetMultiResponse } from '../../services/models/api-response';
import { Column, Sort, SortDirection } from '../../layout/table/table.types';
import { CollectionParameters } from '../../services/models/api-parameter';
import { debounceTime, distinctUntilChanged, finalize, takeUntil, tap } from 'rxjs/operators';
import { ToastService } from '../../layout/toast/toast.service';
import { LoaderService } from 'src/app/core/services/loader.service';

@Component({
  selector: 'cmdb-object',
  templateUrl: './object.component.html',
  styleUrls: ['./object.component.scss']
})
export class ObjectComponent implements OnInit, OnDestroy {

  /**
   * Component un-subscriber.
   * @private
   */
  private subscriber: ReplaySubject<void>;

  /**
   * HTML ID of the table.
   */
  public readonly id: string = 'type-list-table';

  /**
   * Empty table info.
   */
  public readonly emptyTableInformation: string = 'No objects found!';

  /**
   * Default table info.
   */
  public readonly loadingTableInformation: string = 'Objects loading...';

  /**
   * Table info.
   */
  public tableInformation: string = this.emptyTableInformation;

  /**
   * Displayed objects.
   */
  public objects: Array<CmdbObject | RenderResult> = [];

  /**
   * API Response of the objects call.
   */
  public objectsAPIResponse: APIGetMultiResponse<CmdbObject | RenderResult>;

  /**
   * Total number of objects in the database.
   */
  public totalObjects: number = 0;

  /**
   * Columns at the beginning of the loading.
   */
  public initialVisibleColumns: Array<string> = [];

  /**
   * Table columns definition.
   */
  public columns: Array<Column> = [];

  /**
   * Begin with first page.
   */
  public readonly initPage: number = 1;
  public page: number = this.initPage;

  /**
   * Max number of types per site.
   * @private
   */
  private readonly initLimit: number = 25;
  public limit: number = this.initLimit;

  /**
   * Filter query from the table search input.
   */
  public filter: string;

  /**
   * Default sort filter.
   */
  public sort: Sort = { name: 'public_id', order: SortDirection.DESCENDING } as Sort;

  /**
   * Loading indicator.
   */
  public loading: boolean = false;

  /**
   * Table Template: Active column.
   */
  @ViewChild('activeTemplate', { static: true }) activeTemplate: TemplateRef<any>;

  /**
   * Table Template: Type name column.
   */
  @ViewChild('typeNameTemplate', { static: true }) typeNameTemplate: TemplateRef<any>;

  /**
   * Table Template: Type date column.
   */
  @ViewChild('dateTemplate', { static: true }) dateTemplate: TemplateRef<any>;

  /**
   * Table Template: Last edit column.
   */
  @ViewChild('lastEditTemplate', { static: true }) lastEditTemplate: TemplateRef<any>;

  /**
   * Table Template: Action column.
   */
  @ViewChild('actionTemplate', { static: true }) actionTemplate: TemplateRef<any>;

  searchTerms$ = new Subject<string>();

  public isLoading$ = this.loaderService.isLoading$;


  constructor(private objectService: ObjectService<RenderResult>, 
              private toastService: ToastService, 
              private loaderService: LoaderService
) {
    this.subscriber = new ReplaySubject<void>();
  }

  public ngOnInit(): void {
    const columns = [
      {
        display: 'Active',
        name: 'active',
        data: 'object_information.active',
        searchable: false,
        sortable: true,
        template: this.activeTemplate,
        style: { width: '6rem' }
      },
      {
        display: 'Public ID',
        name: 'public_id',
        data: 'object_information.object_id',
        searchable: true,
        sortable: true
      },
      {
        display: 'Type',
        name: 'type.name',
        data: 'type_information',
        searchable: true,
        sortable: true,
        template: this.typeNameTemplate,
      },
      {
        display: 'Summary',
        name: 'summary_line',
        data: 'summary_line',
        searchable: false,
        sortable: false
      },
      {
        display: 'Author',
        name: 'author.user_name',
        data: 'object_information.author_name',
        searchable: true,
        sortable: true
      },
      {
        display: 'Creation',
        name: 'creation_time',
        data: 'object_information.creation_time',
        searchable: true,
        sortable: true,
        template: this.dateTemplate,
      },
      {
        display: 'Last editor',
        name: 'editor.user_name',
        data: 'object_information.editor_name',
        searchable: true,
        sortable: true
      },
      {
        display: 'Last modification',
        name: 'last_edit_time',
        data: 'object_information.last_edit_time',
        searchable: true,
        sortable: true,
        template: this.lastEditTemplate,
      },
      {
        display: 'Actions',
        name: 'actions',
        data: 'object_information.object_id',
        sortable: false,
        searchable: false,
        fixed: true,
        template: this.actionTemplate,
        cssClasses: ['text-center'],
        style: { width: '6em' }
      }
    ] as Array<Column>;
    this.initialVisibleColumns = columns.filter(c => !c.hidden).map(c => c.name);
    this.columns = [...columns];
    this.loadObjectsFromAPI();

    this.searchTerms$
      .pipe(
        debounceTime(300),
        distinctUntilChanged(),
        tap(term => {
          this.filter = term ? term : undefined;
          this.loadObjectsFromAPI();
        })
      )
      .subscribe();

  }

  private setLoadingState(isLoading: boolean) {
    this.loading = isLoading;
    this.tableInformation = this.loading ? this.loadingTableInformation : this.emptyTableInformation;
  }

  /**
   * Load/reload objects from the api.
   * @private
   */
  private loadObjectsFromAPI(): void {
    this.loaderService.show();
    this.setLoadingState(true);
    const filter = this.filterBuilder();
    const params: CollectionParameters = {
      filter, limit: this.limit,
      sort: this.sort.name, order: this.sort.order, page: this.page
    };
    this.objectService.getObjects(params).pipe(takeUntil(this.subscriber), finalize(() => this.loaderService.hide())).subscribe(
      (apiResponse: APIGetMultiResponse<RenderResult>) => {
        this.objectsAPIResponse = apiResponse;
        this.objects = apiResponse.results as Array<RenderResult>;
        this.totalObjects = apiResponse.total;
      },
      (error) => this.toastService.error(error),
      () => this.setLoadingState(false));
  }

  /**
   * * DB Query / Filter Builder
   * Creates a database query using the passed parameters.
   *
   * @return query {@link: any[]}
   */
  private filterBuilder() {
    let query;

    if (this.filter) {
      query = [];
      const or = [];
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

      query.push({
        $project: {
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
        }
      });

      query.push({
        $group: {
          _id: '$_id',
          public_id: { $first: '$public_id' },
          type_id: { $first: '$type_id' },
          active: { $first: '$active' },
          author_id: { $first: '$author_id' },
          creation_time: { $first: '$creation_time' },
          last_edit_time: { $first: '$last_edit_time' },
          fields: { $first: '$fields' },
          simple: { $first: '$simple' },
        }
      });

      query.push({
        $project:
        {
          _id: '$_id',
          public_id: 1,
          type_id: 1,
          active: 1,
          author_id: 1,
          creation_time: 1,
          last_edit_time: 1,
          fields: 1,
          references: { $setUnion: ['$fields', '$simple'] },
        }
      }
      );
      // Search for creation_time
      query.push(
        {
          $addFields: {
            creationString: { $dateToString: { format: '%Y-%m-%dT%H:%M:%S.%LZ', date: '$creation_time' } }
          }
        },
      );
      // Search for last_edit_time
      query.push(
        {
          $addFields: {
            editString: { $dateToString: { format: '%Y-%m-%dT%H:%M:%S.%LZ', date: '$last_edit_time' } }
          }
        },
      );
      // Search date in field values
      query.push(
        {
          $addFields: {
            references: {
              $map: {
                input: '$references',
                as: 'new_fields',
                in: {
                  $cond: [
                    { $eq: [{ $type: '$$new_fields.value' }, 'date'] },
                    {
                      name: '$$new_fields.name', value: {
                        $dateToString: { format: '%Y-%m-%dT%H:%M:%S.%LZ', date: '$$new_fields.value' }
                      }
                    },
                    { name: '$$new_fields.name', value: '$$new_fields.value' }
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
      or.push({ creationString: { $regex: String(this.filter), $options: 'ims' } });
      or.push({ editString: { $regex: String(this.filter), $options: 'ims' } });
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
    this.page = this.initPage;
    this.loadObjectsFromAPI();
  }


  /**
   * On table search change.
   * Reload all objects.
   *
   * @param search
   */
  public onSearchChange(search: any): void {
    this.searchTerms$.next(search);
  }

  /**
   * On delete object call.
   * @param objectID
   */
  public onObjectDelete(objectID: number) {
    this.loaderService.show();
    this.objectService.deleteObject(objectID).pipe(takeUntil(this.subscriber), finalize(() => this.loaderService.hide()))
      .subscribe(() => {
        this.toastService.success(`Object ${objectID} was deleted successfully`);
        this.loadObjectsFromAPI();
      },
        (error) => {
          this.toastService.error(`Error while deleting object ${objectID} | Error: ${error}`);
        });
  }

  public onObjectDeleteWithLocations(objectID: number) {
    this.loaderService.show();
    this.objectService.deleteObjectWithLocations(objectID).pipe(takeUntil(this.subscriber), finalize(() =>  this.loaderService.hide()))
      .subscribe(() => {
        this.toastService.success(`Object ${objectID} and child locations were deleted successfully`);
        this.loadObjectsFromAPI();
      },
        (error) => {
          this.toastService.error(`Error while deleting object ${objectID} | Error: ${error}`);
        });
  }

  public onObjectDeleteWithObjects(objectID: number) {
    this.loaderService.show();
    this.objectService.deleteObjectWithChildren(objectID).pipe(takeUntil(this.subscriber), finalize(() => this.loaderService.hide()))
      .subscribe(() => {
        this.toastService.success(`Object ${objectID} and child locations were deleted successfully`);
        this.loadObjectsFromAPI();
      },
        (error) => {
          this.toastService.error(`Error while deleting object ${objectID} | Error: ${error}`);
        });
  }

  /**
   * Destroy subscriptions after closed.
   */
  public ngOnDestroy(): void {
    this.subscriber?.next();
    this.subscriber?.complete();
  }

}
