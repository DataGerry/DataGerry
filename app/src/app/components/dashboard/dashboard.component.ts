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

import { finalize, ReplaySubject, Subscription, switchMap, takeUntil } from 'rxjs';

import { ObjectService } from '../../framework/services/object.service';
import { ToastService } from '../../layout/toast/toast.service';
import { SidebarService } from '../../layout/services/sidebar.service';

import { APIGetMultiResponse } from '../../services/models/api-response';
import { RenderResult } from '../../framework/models/cmdb-render';
import { Column } from '../../layout/table/table.types';
import { CollectionParameters } from '../../services/models/api-parameter';
import { LoaderService } from 'src/app/core/services/loader.service';
import { environment } from 'src/environments/environment';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'cmdb-dashboard',
    templateUrl: './dashboard.component.html',
    styleUrls: ['./dashboard.component.scss'],
    standalone: false
})
export class DashboardComponent implements OnInit, OnDestroy {

    // Table Template: Dashboard active column
    @ViewChild('activeTemplate', { static: true }) activeTemplate: TemplateRef<any>;
    // Table Template: Dashboard user column
    @ViewChild('userTemplate', { static: true }) userTemplate: TemplateRef<any>;
    // Table Template: Dashboard action column
    @ViewChild('actionTemplate', { static: true }) actionTemplate: TemplateRef<any>;
    // Table Template: Dashboard date column
    @ViewChild('dateTemplate', { static: true }) dateTemplate: TemplateRef<any>;

    private unSubscribe: ReplaySubject<void> = new ReplaySubject();

    public isCloudMode: boolean = environment.cloudMode;

    public objectCount: number = 0;
    public typeCount: number = 0;
    public isCloudMode: boolean = environment.cloudMode;

    public newestObjects: Array<RenderResult> = [];
    public newestTableColumns: Array<Column> = [];
    public newestObjectsCount: number = 0;
    public readonly newestInnitPage: number = 1;
    public newestPage: number = this.newestInnitPage;
    public newestLoading: boolean = false;

    public latestObjects: Array<RenderResult> = [];
    public latestTableColumns: Array<Column> = [];
    public latestObjectsCount: number = 0;
    public readonly latestInnitPage: number = 1;
    public latestPage: number = this.latestInnitPage;
    public latestLoading: boolean = false;

    public readonly maxChartValue: number = 4;

    // Chart Objects
    public labelsObject: string[] = [];
    public itemsObject: number[] = [];
    public colorsObject: any[] = [];

    public totalObjects: number = 0;
    private subscription: Subscription;
    public isLoading$ = this.loaderService.isLoading$;

    /* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    constructor(
        private objectService: ObjectService,
        private toastService: ToastService,
        private sidebarService: SidebarService,
        private loaderService: LoaderService,
    ) {}


    public ngOnInit(): void {
        const activeColumn = {
            display: 'Active',
            name: 'active',
            data: 'object_information.active',
            searchable: false,
            sortable: false,
            template: this.activeTemplate,
            cssClasses: ['text-center'],
            style: { width: '6rem' }
        } as unknown as Column;

        const publicColumn = {
            display: 'Public ID',
            name: 'public_id',
            data: 'object_information.object_id',
            cssClasses: ['text-center'],
            style: { width: '6rem' },
            searchable: false,
            sortable: false
        } as unknown as Column;

        const typeColumn = {
            display: 'Type',
            name: 'type',
            data: 'type_information.type_label',
            cssClasses: ['text-center'],
            searchable: false,
            sortable: false
        } as unknown as Column;

        const authorColumn = {
            display: 'Author',
            name: 'author_id',
            data: 'object_information.author_name',
            sortable: false,
            searchable: false,
            cssClasses: ['text-center']
        } as Column;

        const editorColumn = {
            display: 'Last editor',
            name: 'editor_id',
            data: 'object_information.editor_name',
            sortable: false,
            searchable: false,
            cssClasses: ['text-center'],
            render(data: any) {
                if (!data) {
                    return '';
                }
                return data;
            }
        } as Column;

        const creationColumn = {
            display: 'Creation Time',
            name: 'creation_time',
            data: 'object_information.creation_time',
            sortable: false,
            searchable: false,
            cssClasses: ['text-center'],
            template: this.dateTemplate,
        } as Column;

        const lastModColumn = {
            display: 'Modification Time',
            name: 'last_edit_time',
            data: 'object_information.last_edit_time',
            sortable: false,
            searchable: false,
            cssClasses: ['text-center'],
            template: this.dateTemplate,
            render(data: any) {
                if (!data) {
                    return 'No modifications so far.';
                }
                return data;
            }
        } as Column;

        const actionColumn = {
            display: 'Actions',
            name: 'actions',
            sortable: false,
            searchable: false,
            fixed: true,
            template: this.actionTemplate,
            cssClasses: ['text-center'],
            style: { width: '6em' }
        } as unknown as Column;

        this.newestTableColumns = [activeColumn, publicColumn, typeColumn, authorColumn, creationColumn, actionColumn];
        this.latestTableColumns = [activeColumn, publicColumn, typeColumn, editorColumn, lastModColumn, actionColumn];

        this.countObjects();
        if (this.isCloudMode) {
            this.countTotalObjects();
        }
        this.loadNewestObjects();
        this.loadLatestObjects();

        this.generateObjectChar();

    }


    public ngOnDestroy(): void {
        this.unSubscribe.next();
        this.unSubscribe.complete();
        if (this.subscription) {
            this.subscription.unsubscribe();
        }
    }

    /* --------------------------------------------------- OBJECTS API -------------------------------------------------- */

    /**
     * Returns the number of objects
     */
    private countObjects(): void {
        this.objectService.countObjects().pipe(
            switchMap(() => this.objectService.getLastObjectCount()),
        ).subscribe(count => {
            this.objectCount = count;
        });
    }
    

    /**
     * Retrieves and sets the total number of objects from the service.
     */
    private countTotalObjects(): void {
        this.loaderService.show();
        this.objectService.getConfigItemsLimit().pipe(takeUntil(this.unSubscribe),
        finalize(() => this.loaderService.hide()))
            .subscribe({
                next: (limit) => {
                    this.totalObjects = limit;
                },
                error: (error) => {
                    this.toastService.error(error?.error?.message);
                },
                complete: () => {
                    this.newestLoading = false;          }
            });
    }


    /**
     * Gets newest objects
     */
    private loadNewestObjects(): void {
        this.newestLoading = true;
        this.loaderService.show();
        const apiParameters: CollectionParameters = { page: this.newestPage, limit: 10, order: -1 };
        this.objectService.getNewestObjects(apiParameters).pipe(takeUntil(this.unSubscribe) ,
        finalize(() => this.loaderService.hide()))
            .subscribe({
                next: (apiResponse: APIGetMultiResponse<RenderResult>) => {
                    this.newestObjects = apiResponse.results as Array<RenderResult>;
                    this.newestObjectsCount = apiResponse.total;
                },
                error: (error) => {
                    this.newestLoading = false;
                    this.toastService.error(error?.error?.message);
                },
                complete: () => {
                    this.newestLoading = false;
                }
            });
    }


    private loadLatestObjects(): void {
        this.latestLoading = true;
        this.loaderService.show();
        const apiParameters: CollectionParameters = { page: this.latestPage, limit: 10, order: -1 };
        this.objectService.getLatestObjects(apiParameters).pipe(takeUntil(this.unSubscribe),
        finalize(() => this.loaderService.hide()))
            .subscribe({
                next: (apiResponse: APIGetMultiResponse<RenderResult>) => {
                    this.latestObjects = apiResponse.results as Array<RenderResult>;
                    this.latestObjectsCount = apiResponse.total;
                },
                error: (error) => {
                    this.latestLoading = false;
                    this.toastService.error(`Error while loading latest objects: ${error}`);
                },
                complete: () => {
                    this.latestLoading = false;
                }
            });
    }


    public onObjectDelete(value: RenderResult) {
        this.objectService.deleteObject(value.object_information.object_id).pipe(takeUntil(this.unSubscribe))
            .subscribe({
                next: () => {
                    this.toastService.success(`Object ${value.object_information.object_id} was deleted successfully`);
                    this.sidebarService.updateTypeCounter(value.type_information.type_id).then(() => {
                        this.loadLatestObjects();
                        this.loadNewestObjects();
                    });
                },
                error: (error) => {
                    this.toastService.error(`Error while deleting object ${value.object_information.object_id}: ${error}`);
                }
            });
    }


    /**
     * Deletes the object, the corresponding location and all locations from child objects
     * 
     * @param value object which should be deleted
     */
    public onObjectDeleteWithLocations(value: RenderResult) {
        this.objectService.deleteObjectWithLocations(value.object_information.object_id).pipe(takeUntil(this.unSubscribe))
            .subscribe({
                next: () => {
                    this.toastService.success(`Object ${value.object_information.object_id} was deleted successfully`);
                    this.sidebarService.updateTypeCounter(value.type_information.type_id).then(() => {
                        this.loadLatestObjects();
                        this.loadNewestObjects();
                    });
                },
                error: (error) => {
                    this.toastService.error(`Error while deleting object ${value.object_information.object_id} 
                                             with locations: ${error}`);
                }
            });
    }


    public onObjectDeleteWithObjects(value: RenderResult) {
        this.objectService.deleteObjectWithChildren(value.object_information.object_id).pipe(takeUntil(this.unSubscribe))
            .subscribe({
                next: () => {
                    this.toastService.success(`Object ${value.object_information.object_id} was deleted successfully`);
                    this.sidebarService.updateTypeCounter(value.type_information.type_id).then(() => {
                        this.loadLatestObjects();
                        this.loadNewestObjects();
                    });
                },
                error: (error) => {
                    this.toastService.error(`Error while deleting object ${value.object_information.object_id}
                                             with child objects: ${error}`);
                }
            });
    }

    /* ----------------------------------------------- OBJECT API - HELPER ---------------------------------------------- */

    public onNewestPageChange(event) {
        this.newestPage = event;
        this.loadNewestObjects();
    }


    public onLatestPageChange(event) {
        this.latestPage = event;
        this.loadLatestObjects();
    }

    /* ------------------------------------------------ CHARTS FUNCTIONS ------------------------------------------------ */

    private generateObjectChar(): void {
        this.loaderService.show();
        this.objectService.groupObjectsByType('type_id').pipe(takeUntil(this.unSubscribe),
        finalize(() => this.loaderService.hide()))
            .subscribe({
                next: (values) => {
                    for (const obj of values) {
                        this.labelsObject.push(obj.label);
                        this.colorsObject.push(obj.type_color);
                        this.itemsObject.push(obj.count);
                    }
                },
                error: (error) => {
                    this.toastService.error(error?.error?.message);
                }
            });
    }


    getRandomColor() {
        const color = Math.floor(0x1000000 * Math.random()).toString(16);
        return '#' + ('000000' + color).slice(-6);
    }
}
