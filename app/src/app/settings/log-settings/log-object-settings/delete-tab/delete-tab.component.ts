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
*
* You should have received a copy of the GNU Affero General Public License
* along with this program. If not, see <https://www.gnu.org/licenses/>.
*/
import { Component, EventEmitter, Input, OnDestroy, OnInit, Output, TemplateRef, ViewChild } from '@angular/core';
import { ActivatedRoute, Data, Router } from '@angular/router';

import { BehaviorSubject, ReplaySubject } from 'rxjs';
import { finalize, takeUntil } from 'rxjs/operators';

import { LogService } from '../../../../framework/services/log.service';
import {
    convertResourceURL,
    UserSettingsService
} from '../../../../management/user-settings/services/user-settings.service';
import { UserSettingsDBService } from '../../../../management/user-settings/services/user-settings-db.service';

import { CmdbLog } from '../../../../framework/models/cmdb-log';
import { Column, Sort, SortDirection, TableState, TableStatePayload } from '../../../../layout/table/table.types';
import { CollectionParameters } from '../../../../services/models/api-parameter';
import { APIGetMultiResponse } from '../../../../services/models/api-response';
import { TableComponent } from '../../../../layout/table/table.component';
import { UserSetting } from '../../../../management/user-settings/models/user-setting';
import { LoaderService } from 'src/app/core/services/loader.service';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'cmdb-delete-tab',
    templateUrl: './delete-tab.component.html',
    styleUrls: ['./delete-tab.component.scss']
})
export class DeleteTabComponent implements OnInit, OnDestroy {

    @Output() deleteEmitter = new EventEmitter<number>();
    @Output() cleanUpEmitter = new EventEmitter<number[]>();

    private subscriber: ReplaySubject<void> = new ReplaySubject<void>();

    @ViewChild(TableComponent) objectsTableComponent: TableComponent<CmdbLog>;
    @ViewChild('dateTemplate', { static: true }) dateTemplate: TemplateRef<any>;
    @ViewChild('dataTemplate', { static: true }) dataTemplate: TemplateRef<any>;
    @ViewChild('changeTemplate', { static: true }) changeTemplate: TemplateRef<any>;
    @ViewChild('userTemplate', { static: true }) userTemplate: TemplateRef<any>;

    @Input() set reloadLogs(value: boolean) {
        if (value) {
            this.resetCollectionParameters();
            this.loadDeleted();
        }
    }

    public selectedLogIDs: Array<number> = [];
    public filter: string;
    public deleteLogList: CmdbLog[] = [];
    public columns: Array<Column>;
    public sort: Sort = { name: 'public_id', order: SortDirection.ASCENDING } as Sort;

    private readonly initLimit: number = 10;
    public limit: number = this.initLimit;

    public readonly initPage: number = 1;
    public page: number = this.initPage;

    public total: number = 0;
    public loading: boolean = false;

    public apiParameters: CollectionParameters = { limit: 10, sort: 'log_time', order: -1, page: 1 };

    // The Id used for the table
    public id: string = 'object-deleted-log-list-table';

    public tableStateSubject: BehaviorSubject<TableState> = new BehaviorSubject<TableState>(undefined);
    public tableStates: Array<TableState> = [];

    public get tableState(): TableState {
        return this.tableStateSubject.getValue() as TableState;
    }

    public isLoading$ = this.loaderService.isLoading$;


/* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    constructor(private logService: LogService,
                private route: ActivatedRoute,
                private router: Router,
                private userSettingsService: UserSettingsService<UserSetting, TableStatePayload>,
                private indexDB: UserSettingsDBService<UserSetting, TableStatePayload>,
                private loaderService: LoaderService) {

        this.route.data.pipe(takeUntil(this.subscriber)).subscribe((data: Data) => {
            if (data.userSetting) {
                const userSettingPayloads = (data.userSetting as UserSetting<TableStatePayload>).payloads
                    .find(payloads => payloads.id === this.id);

                if (userSettingPayloads) {
                    this.tableStates = userSettingPayloads.tableStates;
                    this.tableStateSubject.next(userSettingPayloads.currentState);
                }
            } else {
                this.tableStates = [];
                this.tableStateSubject.next(undefined);

                const statePayload: TableStatePayload = new TableStatePayload(this.id, []);
                const resource: string = convertResourceURL(this.router.url.toString());
                const userSetting = userSettingsService.createUserSetting<TableStatePayload>(resource, [statePayload]);
                this.indexDB.addSetting(userSetting);
            }
        });
    }


    public ngOnInit(): void {
        this.resetCollectionParameters();
        this.setColumns();
        this.initTable();
        this.loadDeleted();
    }


    public ngOnDestroy(): void {
        this.subscriber?.next();
        this.subscriber?.complete();
    }

/* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    private loadDeleted() {
        this.loaderService.show();
        const filter = JSON.stringify(this.filterBuilder());
        this.apiParameters = {
            filter,
            limit: this.limit,
            sort: this.sort.name,
            order: this.sort.order,
            page: this.page
        };

        this.logService.getDeleteLogs(this.apiParameters).pipe(takeUntil(this.subscriber), finalize(() => this.loaderService.hide()))
            .subscribe((apiResponse: APIGetMultiResponse<CmdbLog>) => {
                this.deleteLogList = apiResponse.results;
                this.total = apiResponse.total;
            });
    }


    private initTable() {
        if (this.tableState) {
            this.sort = this.tableState.sort;
            this.limit = this.tableState.pageSize;
            this.page = this.tableState.page;
        }
    }


    private resetCollectionParameters(): void {
        this.apiParameters = { limit: 10, sort: 'date', order: -1, page: 1 };
    }


    private setColumns(): void {
        const columns = [];

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
            display: 'Object ID',
            name: 'object_id',
            data: 'object_id',
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
            searchable: true,
            fixed: true,
            template: this.dataTemplate,
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
            cssClasses: ['text-center'],
            style: { width: '6em' }
        } as unknown as Column);

        columns.push({
            display: 'Comment',
            name: 'comment',
            data: 'comment',
            sortable: true,
            searchable: false,
            fixed: true,
            template: this.dataTemplate,
            cssClasses: ['text-center'],
            style: { width: '6em' }
        } as unknown as Column);

        columns.push({
            display: 'Author',
            data: 'author_name',
            name: 'author_name',
            sortable: true,
            searchable: true,
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
            template: this.dataTemplate,
            cssClasses: ['text-center'],
            style: { width: '6em' }
        } as unknown as Column);

        columns.push({
                display: 'Log Time',
                name: 'log_time',
                data: 'log_time',
                sortable: true,
                cssClasses: ['text-center'],
                style: { 'white-space': 'nowrap' },
                template: this.dateTemplate,
                searchable: false,
        } as Column);

        this.columns = columns;
    }


    public onPageChange(page: number) {
        this.page = page;
        this.loadDeleted();
    }


    public onPageSizeChange(limit: number): void {
        this.limit = limit;
        this.loadDeleted();
    }


    public onSortChange(sort: Sort): void {
        this.sort = sort;
        this.loadDeleted();
    }


    public onSearchChange(search: any): void {
        if (search) {
            this.filter = search;
        } else {
            this.filter = undefined;
        }
        this.loadDeleted();
    }


    public onSelectedChange(selectedItems: Array<CmdbLog>): void {
        this.selectedLogIDs = selectedItems.map(m => m.public_id);
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

            query.push({ $match: { $and: [{ log_type: 'CmdbObjectLog' }, { $or: or }] } });
        } else {
            query.push({ $match: { log_type: 'CmdbObjectLog' } });
        }

        return query;
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
        this.loadDeleted();
    }


    /**
     * On table State change.
     * Update state.
     */
    public onStateChange(state: TableState): void {
        this.tableStateSubject.next(state);
    }


    /**
     * On table State change.
     * Update state.
     */
    public onStateReset(): void {
        this.sort = { name: 'public_id', order: SortDirection.DESCENDING } as Sort;
        this.limit = this.initLimit;
        this.page = this.initPage;
        this.loadDeleted();
    }


    public cleanup() {
        this.cleanUpEmitter.emit(this.selectedLogIDs);
        this.objectsTableComponent.selectedItems = [];
        this.selectedLogIDs = [];
    }
}
