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
import { Component, OnDestroy, OnInit, TemplateRef, ViewChild } from '@angular/core';
import { DatePipe } from '@angular/common';
import { ActivatedRoute, Data, Router } from '@angular/router';

import { BehaviorSubject, ReplaySubject } from 'rxjs';
import { finalize, takeUntil } from 'rxjs/operators';

import { FileSaverService } from 'ngx-filesaver';

import { TypeService } from '../services/type.service';
import { FileService } from '../../export/export.service';
import { PermissionService } from '../../modules/auth/services/permission.service';
import { convertResourceURL, UserSettingsService } from '../../management/user-settings/services/user-settings.service';
import { UserSettingsDBService } from '../../management/user-settings/services/user-settings-db.service';

import { APIGetMultiResponse } from '../../services/models/api-response';
import { CmdbType } from '../models/cmdb-type';
import { Column, Sort, SortDirection, TableState, TableStatePayload } from '../../layout/table/table.types';
import { CollectionParameters } from '../../services/models/api-parameter';
import { UserSetting } from '../../management/user-settings/models/user-setting';
import { SidebarService } from 'src/app/layout/services/sidebar.service';
import { LoaderService } from 'src/app/core/services/loader.service';
import { ToastService } from 'src/app/layout/toast/toast.service';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'cmdb-type',
    templateUrl: './type.component.html',
    styleUrls: ['./type.component.scss']
})
export class TypeComponent implements OnInit, OnDestroy {

    // HTML ID of the table. Used for user settings and table-states
    public readonly id: string = 'type-list-table';

    // Global un-subscriber for http calls to the rest backend.
    private subscriber: ReplaySubject<void> = new ReplaySubject<void>();

    // Current category collection
    public types: Array<CmdbType> = [];
    public typesAPIResponse: APIGetMultiResponse<CmdbType>;
    public totalTypes: number = 0;

    // Type selection
    public selectedTypes: Array<CmdbType> = [];
    public selectedTypeIDs: Array<number> = [];

    // Table Template: active column
    @ViewChild('activeTemplate', { static: true }) activeTemplate: TemplateRef<any>;
    // Table Template: Type name column
    @ViewChild('typeNameTemplate', { static: true }) typeNameTemplate: TemplateRef<any>;
    // Table Template: Type actions column
    @ViewChild('actionsTemplate', { static: true }) actionsTemplate: TemplateRef<any>;
    // Table Template: Type clean column
    @ViewChild('cleanTemplate', { static: true }) cleanTemplate: TemplateRef<any>;
    // Table Template: Type date column
    @ViewChild('dateTemplate', { static: true }) dateTemplate: TemplateRef<any>;
    // Table Template: user column
    @ViewChild('userTemplate', { static: true }) userTemplate: TemplateRef<any>;

    // Table columns definition
    public columns: Array<Column>;

    // Table selection enabled
    public selectEnabled: boolean = false;

    // Begin with first page
    public readonly initPage: number = 1;
    public page: number = this.initPage;

    // Max number of types per site
    private readonly initLimit: number = 10;
    public limit: number = this.initLimit;

    // Filter query from the table search input
    public filter: string;

    // Default sort filter
    public sort: Sort = { name: 'public_id', order: SortDirection.DESCENDING } as Sort;

    // Loading indicator
    public loading: boolean = false;
    public isLoading$ = this.loaderService.isLoading$;

    public tableStateSubject: BehaviorSubject<TableState> = new BehaviorSubject<TableState>(undefined);
    public tableStates: Array<TableState> = [];


    /* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    constructor(
        private typeService: TypeService,
        private fileService: FileService,
        private route: ActivatedRoute,
        private permissionService: PermissionService,
        private fileSaverService: FileSaverService,
        private datePipe: DatePipe,
        private router: Router,
        private userSettingsService: UserSettingsService<UserSetting, TableStatePayload>,
        private indexDB: UserSettingsDBService<UserSetting, TableStatePayload>,
        private sideBarService: SidebarService,
        private loaderService: LoaderService,
        private toastService: ToastService
    ) {

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


    /**
     * Starts the component and init the table
     */
    public ngOnInit(): void {
        this.columns = [
            {
                display: 'Active',
                name: 'active',
                data: 'active',
                searchable: false,
                sortable: true,
                template: this.activeTemplate,
                cssClasses: ['text-center'],
                style: { width: '6rem' }
            },
            {
                display: 'Public ID',
                name: 'public_id',
                data: 'public_id',
                searchable: true,
                sortable: true
            },
            {
                display: 'Type',
                name: 'name',
                data: 'name',
                searchable: true,
                sortable: true,
                template: this.typeNameTemplate,
            },
            {
                display: 'Author',
                name: 'author_id',
                data: 'author_id',
                searchable: true,
                sortable: true,
                template: this.userTemplate
            },
            {
                display: 'Creation Time',
                name: 'creation_time',
                data: 'creation_time',
                sortable: true,
                searchable: false,
                template: this.dateTemplate,
            },
            {
                display: 'Last editor',
                name: 'editor_id',
                data: 'editor_id',
                sortable: true,
                searchable: true,
                template: this.userTemplate
            },
            {
                display: 'Modification Time',
                name: 'last_edit_time',
                data: 'last_edit_time',
                sortable: true,
                searchable: false,
                template: this.dateTemplate,
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
            },
        ] as Array<Column>;

        const cleanRight = 'base.framework.type.clean';
        if (this.permissionService.hasRight(cleanRight) || this.permissionService.hasExtendedRight(cleanRight)) {
            this.columns.push({
                display: 'Clean',
                name: 'clean',
                searchable: false,
                sortable: false,
                fixed: true,
                template: this.cleanTemplate,
                cssClasses: ['text-center'],
                cellClasses: ['text-center']
            } as Column);
        }

        const exportRight = 'base.export.type.*';
        if (this.permissionService.hasRight(exportRight) || this.permissionService.hasExtendedRight(exportRight)) {
            this.selectEnabled = true;
        }

        this.initTable();
        this.loadTypesFromAPI();
    }


    /**
     * Destroy subscriptions after closed.
     */
    public ngOnDestroy(): void {
        this.subscriber?.next();
        this.subscriber?.complete();
    }

    /* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    public get tableState(): TableState {
        return this.tableStateSubject.getValue() as TableState;
    }


    /**
     * If a table state is available configures the
     * table according to the data specified in the table state
     */
    private initTable() {
        if (this.tableState) {
            this.sort = this.tableState.sort;
            this.page = this.tableState.page;
            this.limit = this.tableState.pageSize;
        }
    }


    /**
     * Load/reload types from the api
     */
    private loadTypesFromAPI(): void {
        this.loading = true;
        this.loaderService.show()
        let query;

        if (this.filter) {
            query = [];
            const or = [];
            const searchableColumns = this.columns.filter(c => c.searchable);

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

            or.push({
                public_id: {
                    $elemMatch: {
                        value: {
                            $regex: String(this.filter),
                            $options: 'ismx'
                        }
                    }
                }
            });

            query.push({ $match: { $or: or } });
        }

        const params: CollectionParameters = {
            filter: query,
            limit: this.limit,
            sort: this.sort.name,
            order: this.sort.order,
            page: this.page
        };

        this.typeService.getTypes(params).pipe(takeUntil(this.subscriber), finalize(() => this.loaderService.hide())).subscribe(
            {
                next: (apiResponse: APIGetMultiResponse<CmdbType>) => {
                    this.typesAPIResponse = apiResponse;
                    this.types = apiResponse?.results as Array<CmdbType>;
                    this.totalTypes = apiResponse?.total;
                    this.loading = false;
                    this.sideBarService?.loadCategoryTree();

                },
                error: (error) => {
                    this.loading = false;
                    this.toastService?.error(error?.error?.message)
                }
            }
        );
    }


    /**
     * On table sort change.
     * Reload all types.
     *
     * @param sort
     */
    public onSortChange(sort: Sort): void {
        this.sort = sort;
        this.loadTypesFromAPI();
    }


    onStateReset(): void {
        this.limit = this.initLimit;
        this.page = this.initPage;
        this.sort = { name: 'public_id', order: SortDirection.DESCENDING } as Sort;
    }


    /**
     * On table selection change.
     * Map selected items by the object id
     *
     * @param selectedItems
     */
    public onSelectedChange(selectedItems: Array<CmdbType>): void {
        this.selectedTypes = selectedItems;
        this.selectedTypeIDs = selectedItems.map(t => t.public_id);
    }


    /**
     * On table page change.
     * Reload all types.
     *
     * @param page
     */
    public onPageChange(page: number) {
        this.page = page;
        this.loadTypesFromAPI();
    }

    /**
     * On table page size change.
     * Reload all types.
     *
     * @param limit
     */
    public onPageSizeChange(limit: number): void {
        this.limit = limit;
        this.loadTypesFromAPI();
    }


    /**
     * On table search change.
     * Reload all types.
     *
     * @param search
     */
    public onSearchChange(search: any): void {
        if (search) {
            this.filter = search;
        } else {
            this.filter = undefined;
        }

        this.loadTypesFromAPI();
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

        for (const col of this.columns) {
            col.hidden = !this.tableState.visibleColumns.includes(col.name);
        }

        this.loadTypesFromAPI();
    }


    /**
     * Download the selected export file
     *
     * @param data Data which will be exported
     * @param exportType File extension
     */
    public downLoadFile(data: any, exportType: any) {
        const timestamp = this.datePipe.transform(new Date(), 'MM_dd_yyyy_hh_mm_ss');
        this.fileSaverService.save(data.body, timestamp + '.' + exportType);
    }


    /**
     * Call the export routes with the selected types
     */
    public exportingFiles() {

        if (this.selectedTypeIDs.length === 0 || this.selectedTypeIDs.length === this.totalTypes) {
            this.fileService.getTypeFile().subscribe(res => this.downLoadFile(res, 'json'));
        } else {
            this.fileService.callExportTypeRoute('/export/type/' + this.selectedTypeIDs.toString())
                .subscribe(res => this.downLoadFile(res, 'json'));
        }
    }
}