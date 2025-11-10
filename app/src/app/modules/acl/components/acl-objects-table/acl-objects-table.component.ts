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
import { Component, Input, OnDestroy, OnInit, TemplateRef, ViewChild } from '@angular/core';
import { UntypedFormControl, UntypedFormGroup } from '@angular/forms';

import { ReplaySubject, takeUntil } from 'rxjs';

import { TypeService } from 'src/app/framework/services/type.service';
import { PermissionService } from 'src/app/modules/auth/services/permission.service';

import { Group } from 'src/app/management/models/group';
import { CmdbType } from 'src/app/framework/models/cmdb-type';
import { APIGetMultiResponse } from 'src/app/services/models/api-response';
import { Column, Sort, SortDirection } from 'src/app/layout/table/table.types';
import { CollectionParameters } from 'src/app/services/models/api-parameter';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'cmdb-acl-objects-table',
    templateUrl: './acl-objects-table.component.html',
    styleUrls: ['./acl-objects-table.component.scss'],
    standalone: false
})
export class AclObjectsTableComponent implements OnInit, OnDestroy {

    private subscriber: ReplaySubject<void> = new ReplaySubject<void>();

    @Input('group')
    public set Group(group: Group) {
        this.group = group;
        this.loadTypesFromAPI();
    }

    // Passed group
    public group: Group;

    public activatedForm = new UntypedFormGroup({
        active: new UntypedFormControl(false)
    });

    // Table Template: Type name column.
    @ViewChild('typeNameTemplate', { static: true }) public typeNameTemplate: TemplateRef<any>;
    // Table Template: Type ACL column.
    @ViewChild('aclActivateTemplate', { static: true }) public aclActivateTemplate: TemplateRef<any>;
    // Table Template: Type ACL permissions column.
    @ViewChild('aclPermissionsTemplate', { static: true }) public aclPermissionsTemplate: TemplateRef<any>;
    // Table Template: Only active button.
    @ViewChild('activatedButtonTemplate', { static: true }) public activatedButtonTemplate: TemplateRef<any>;
    // Table Template: Type edit action column.
    @ViewChild('aclTypeEditTemplate', { static: true }) public aclTypeEditTemplate: TemplateRef<any>;

    public types: Array<CmdbType> = [];
    public typesAPIResponse: APIGetMultiResponse<CmdbType>;
    public totalTypes: number = 0;

    // Filter query from the table search input.
    public filter: string;

    // Begin with first page.
    public readonly initPage: number = 1;
    public page: number = this.initPage;

    // Max number of types per site.
    private readonly initLimit: number = 10;
    public limit: number = this.initLimit;

    public sort: Sort = { name: 'public_id', order: SortDirection.DESCENDING } as Sort;

    // Table columns definition.
    public columns: Array<Column>;

    // Loading indicator
    public loading: boolean = false;

    public get activeControl(): UntypedFormControl {
        return this.activatedForm.get('active') as UntypedFormControl;
    }

/* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    constructor(private typeService: TypeService, private permissionService: PermissionService) {

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
                display: 'Type',
                name: 'name',
                data: 'name',
                searchable: true,
                sortable: true,
                template: this.typeNameTemplate,
            },
            {
                display: 'ACL',
                name: 'acl',
                data: 'acl',
                searchable: false,
                sortable: true,
                template: this.aclActivateTemplate,
            },
            {
                display: 'Permissions',
                name: 'acl.groups.includes',
                data: 'acl',
                searchable: false,
                sortable: false,
                template: this.aclPermissionsTemplate
            }
        ] as Array<Column>;

        const typeEditRight = 'base.framework.type.edit';

        if (this.permissionService.hasRight(typeEditRight) ||
            this.permissionService.hasExtendedRight(typeEditRight)) {
                this.columns.push({
                    display: 'Actions',
                    name: 'actions',
                    searchable: false,
                    sortable: false,
                    fixed: true,
                    template: this.aclTypeEditTemplate,
                    cssClasses: ['text-center'],
                    cellClasses: ['actions-buttons']
                } as Column);
        }

        this.loadTypesFromAPI();
        this.activatedForm.valueChanges.pipe(takeUntil(this.subscriber)).subscribe(() => {
            this.page = 1;
            this.loadTypesFromAPI();
        });
    }


    public ngOnDestroy(): void {
        this.subscriber?.next();
        this.subscriber?.complete();
    }

/* ------------------------------------------------ HELPER FUNCTIONS ------------------------------------------------ */

    private loadTypesFromAPI(): void {
        this.loading = true;
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
                    public_id: {
                        $toString: '$public_id'
                    }
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

        if (this.activeControl.value) {
            const activeMatch = {
                $match: {
                    acl: {
                        $exists: true
                    },
                    'acl.activated': true
                }
            };

            if (!query) {
                query = [];
            }

            query.push(activeMatch);
        }

        const params: CollectionParameters = {
            filter: query,
            limit: this.limit,
            sort: this.sort.name,
            order: this.sort.order,
            page: this.page
        };

        this.typeService.getTypes(params).pipe(takeUntil(this.subscriber))
            .subscribe((apiResponse: APIGetMultiResponse<CmdbType>) => {
                this.typesAPIResponse = apiResponse;
                this.types = apiResponse.results as Array<CmdbType>;
                this.totalTypes = apiResponse.total;
                this.loading = false;
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
        this.page = 1;
        this.loadTypesFromAPI();
    }


    /**
     * On table search change.
     * Reload all types.
     *
     * @param search
     */
    public onSearchChange(search: any): void {
        this.page = 1;
        if (search) {
        this.filter = search;
        } else {
        this.filter = undefined;
        }
        this.loadTypesFromAPI();
    }
}