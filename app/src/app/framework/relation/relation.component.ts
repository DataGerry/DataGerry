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
*
* You should have received a copy of the GNU Affero General Public License
* along with this program. If not, see <https://www.gnu.org/licenses/>.
*/
import { Component, inject, OnDestroy, OnInit, TemplateRef, ViewChild } from '@angular/core';
import { finalize, takeUntil } from 'rxjs/operators';


import { APIGetMultiResponse } from '../../services/models/api-response';
import { Column, Sort, SortDirection} from '../../layout/table/table.types';
import { CollectionParameters } from '../../services/models/api-parameter';
import { LoaderService } from 'src/app/core/services/loader.service';
import { RelationService } from '../services/relaion.service';
import { CmdbRelation } from '../models/relation.model';
import { ReplaySubject } from 'rxjs';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'cmdb-relation',
    templateUrl: './relation.component.html',
    styleUrls: ['./relation.component.scss'],
    standalone: false
})
export class RelationComponent implements OnInit, OnDestroy {

    private readonly relationService = inject(RelationService);
    private readonly loaderService = inject(LoaderService);

    // HTML ID of the table. Used for user settings and table-states
    public readonly id: string = 'relation-list-table';

    // Global un-subscriber for http calls to the rest backend.
    private subscriber: ReplaySubject<void> = new ReplaySubject<void>();

    // Current category collection
    public relations: Array<CmdbRelation> = [];
    public relationsAPIResponse: APIGetMultiResponse<CmdbRelation>;
    public totalRelations: number = 0;

    // Relation selection
    public selectedRelations: Array<CmdbRelation> = [];
    public selectedRelationIDs: Array<number> = [];


    // Table Template: Relation actions column
    @ViewChild('actionsTemplate', { static: true }) actionsTemplate: TemplateRef<any>;
    // Table Template: Relation description column
    @ViewChild('descriptionTemplate', { static: true }) descriptionTemplate: TemplateRef<any>;


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


    /* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    /**
     * Starts the component and init the table
     */
    public ngOnInit(): void {

        this.columns = [
            {
                display: 'Public ID',
                name: 'public_id',
                data: 'public_id',
                searchable: true,
                sortable: true,
                style: { width: '100px', 'text-align': 'center' }
            },
            {
                display: 'Relation',
                name: 'name',
                data: 'relation_name',
                searchable: true,
                sortable: true,
                style: { width: '45%', 'text-align': 'center' } 
            },
            {
                display: 'Description',
                name: 'description',
                data: 'description',
                sortable: true,
                searchable: false,
                template: this.descriptionTemplate,
                style: { width: '45%', 'text-align': 'center' } 
            },
            {
                display: 'Actions',
                name: 'actions',
                searchable: false,
                sortable: false,
                fixed: true,
                template: this.actionsTemplate,
                style: { width: '100px', 'text-align': 'center' }
            },
        ] as Array<Column>;

        this.loadRelationsFromAPI();
    }


    /**
     * Destroy subscriptions after closed.
     */
    public ngOnDestroy(): void {
        this.subscriber?.next();
        this.subscriber?.complete();
    }

    /* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    /**
     * Load/reload types from the api
     */
    private loadRelationsFromAPI(): void {
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

        this.relationService.getRelations(params).pipe(takeUntil(this.subscriber), finalize(() => this.loaderService.hide())).subscribe(
            (apiResponse: APIGetMultiResponse<CmdbRelation>) => {
                this.relationsAPIResponse = apiResponse;
                this.relations = apiResponse.results as Array<CmdbRelation>;
                this.totalRelations = apiResponse.total;
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
        this.loadRelationsFromAPI();
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
    public onSelectedChange(selectedItems: Array<CmdbRelation>): void {
        this.selectedRelations = selectedItems;
        this.selectedRelationIDs = selectedItems.map(t => t.public_id);
    }


    /**
     * On table page change.
     * Reload all types.
     *
     * @param page
     */
    public onPageChange(page: number) {
        this.page = page;
        this.loadRelationsFromAPI();
    }

    /**
     * On table page size change.
     * Reload all types.
     *
     * @param limit
     */
    public onPageSizeChange(limit: number): void {
        this.limit = limit;
        this.loadRelationsFromAPI();
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

        this.loadRelationsFromAPI();
    }
}