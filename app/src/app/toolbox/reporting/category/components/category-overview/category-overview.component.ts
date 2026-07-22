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
<<<<<<< HEAD
import { Component, OnInit, OnDestroy, TemplateRef, ViewChild } from '@angular/core';
=======
import { Component, inject, OnInit, OnDestroy, TemplateRef, ViewChild } from '@angular/core';
>>>>>>> origin/version-3.2

import { ReplaySubject } from 'rxjs';
import { finalize, takeUntil } from 'rxjs/operators';
import { CollectionParameters } from 'src/app/services/models/api-parameter';
import { APIGetMultiResponse } from 'src/app/services/models/api-response';
import { AddCategoryModalComponent } from '../category-add-modal/category-add-modal.component';
import { NgbModal } from '@ng-bootstrap/ng-bootstrap';
import { Sort, SortDirection } from 'src/app/layout/table/table.types';
import { Location } from '@angular/common';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { LoaderService } from 'src/app/core/services/loader.service';
import { ReportCategoryService } from '../../../services/report-category.service';

@Component({
    selector: 'app-category-overview',
    templateUrl: './category-overview.component.html',
    styleUrls: ['./category-overview.component.scss'],
    standalone: false
})
export class CategoryOverviewComponent implements OnInit, OnDestroy {
<<<<<<< HEAD
=======
    private readonly categoryService = inject(ReportCategoryService);
    private readonly modalService = inject(NgbModal);
    private readonly location = inject(Location);
    private readonly toast = inject(ToastService);
    private readonly loaderService = inject(LoaderService);

>>>>>>> origin/version-3.2
    private unsubscribe$ = new ReplaySubject<void>(1);
    public categories: Array<any> = [];
    public totalCategories: number = 0;
    public limit: number = 10;
    public page: number = 1;
    public loading: boolean = false;
    public sort: Sort = { name: 'public_id', order: SortDirection.ASCENDING } as Sort;
    public filter: string;
    public columns: Array<any>;
    public isLoading$ = this.loaderService.isLoading$;

    @ViewChild('actionsTemplate', { static: true }) actionsTemplate: TemplateRef<any>;

    /* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

<<<<<<< HEAD
    constructor(
        private categoryService: ReportCategoryService,
        private modalService: NgbModal, 
        private location: Location,
        private toast: ToastService,
        private loaderService: LoaderService) { }


=======
>>>>>>> origin/version-3.2
    ngOnInit(): void {
        this.columns = [
            { display: 'Public ID', name: 'public_id', data: 'public_id', searchable: true, sortable: true, style: { width: '120px', 'text-align': 'center' } },
            { display: 'Name', name: 'name', data: 'name', searchable: true, sortable: true, style: { width: 'auto', 'text-align': 'center' } },
            { display: 'Actions', name: 'actions', template: this.actionsTemplate, sortable: false, style: { width: '100px', 'text-align': 'center' } }
        ];

        this.loadCategories();
    }


    ngOnDestroy(): void {
        this.unsubscribe$?.next();
        this.unsubscribe$?.complete();
    }

    /* --------------------------------------------------- REPORT CATEGORY API -------------------------------------------------- */

    /**
     * Loads the list of categories with specified parameters.
     */
    private loadCategories(): void {
        this.loaderService.show();
        this.loading = true;
        const params: CollectionParameters = {
            filter: this.filterBuilder(),
            limit: this.limit,
            page: this.page,
            sort: this.sort.name === 'public_id_str' ? 'public_id' : this.sort.name,
            order: this.sort.order
        };
        this.categoryService.getAllCategories(params).pipe(takeUntil(this.unsubscribe$), finalize(() => this.loaderService.hide())).subscribe(
            (response: APIGetMultiResponse<any>) => {
                this.categories = response.results;
                this.totalCategories = response.total;
                this.loading = false;
            }
        );
    }


    /**
     * Deletes a category by ID after user confirmation.
     * Reloads the category list on successful deletion, or logs an error if deletion fails.
     * @param id - The ID of the category to delete.
     */
    public deleteCategory(id: number): void {
        if (confirm('Are you sure you want to delete this category?')) {
            this.loaderService.show();
            this.categoryService.deleteCategory(id)
                .pipe(takeUntil(this.unsubscribe$), finalize(() => this.loaderService.hide()))
                .subscribe({
                    next: () => {
                        alert('Category deleted successfully');
                        this.loadCategories();
                    },
                    error: (error) => {
                        this.toast.error(error?.error?.message);
                    },
                });
        }
    }

    /* ------------------------------------------------ SORTING AND PAGINATION ------------------------------------------------ */

    /**
     * Handles pagination by updating the current page and reloading the categories.
     * @param newPage - The new page number to load.
     */
    public onPageChange(newPage: number): void {
        this.page = newPage;
        this.loadCategories();
    }


    /**
     * Updates the sort criteria and reloads the categories.
     * @param sort - The new sort criteria.
     */
    public onSortChange(sort: Sort): void {
        this.sort = sort;
        this.loadCategories();
    }


    /**
     * Handles search input changes, updates the filter, resets to the first page, and reloads categories.
     * @param search - The search input value.
     */
    public onSearchChange(search: any): void {
        if (search) {
            this.filter = search;
        } else {
            this.filter = undefined;
        }
        this.page = 1; // Reset to first page when search changes
        this.loadCategories();
    }


    /**
     * Handles changes to the page size, updates the limit, resets to the first page, and reloads categories.
     * @param limit - The new number of items per page.
     */
    public onPageSizeChange(limit: number): void {
        this.limit = limit;
        this.page = 1; // Reset to first page when page size changes
        this.loadCategories();
    }

    /* ------------------------------------------------ REST OF THE FUNCTIONS ------------------------------------------------ */

    /**
     * Builds a MongoDB aggregation pipeline based on the current filter.
     * @returns An aggregation pipeline array.
     */
    private filterBuilder(): any[] {
        const query: any[] = [];

        if (this.filter) {
            const searchableColumns = this.columns.filter(c => c.searchable);
            const or: any[] = [];

            const addFields: any = {};

            for (const column of searchableColumns) {
                let fieldName = column.data || column.name;
                let searchField = fieldName;

                // Convert numeric fields to strings
                if (fieldName === 'public_id') {
                    addFields['public_id_str'] = { $toString: '$public_id' };
                    searchField = 'public_id_str';
                }

                const regexCondition: any = {};
                regexCondition[searchField] = {
                    $regex: String(this.filter),
                    $options: 'i'
                };
                or.push(regexCondition);
            }

            if (Object.keys(addFields).length > 0) {
                query.push({ $addFields: addFields });
            }

            query.push({
                $match: {
                    $or: or
                }
            });
        }

        return query;
    }


    /**
     * Opens the Add Category modal in 'add' mode.
     * Reloads categories on successful addition.
     */
    public openAddCategoryModal(): void {
        const modalRef = this.modalService.open(AddCategoryModalComponent, { size: 'lg' });
        modalRef.componentInstance.mode = 'add';
        modalRef.result.then(
            (result) => {
                if (result === 'success') {
                    this.loadCategories();
                }
            }
        );
    }


    /**
     * Opens the Edit Category modal in 'edit' mode with the selected category's data.
     * Reloads categories on successful update.
     * @param category - The category to edit.
     */
    public openEditCategoryModal(category: any): void {
        const modalRef = this.modalService.open(AddCategoryModalComponent, { size: 'lg' });
        modalRef.componentInstance.mode = 'edit';
        modalRef.componentInstance.categoryData = { ...category };
        modalRef.result.then(
            (result) => {
                if (result === 'updated') {
                    this.loadCategories();
                }
            }
        );
    }


    /**
     * Opens the Delete Category modal in 'delete' mode with the selected category's data.
     * Reloads categories on successful deletion.
     * @param category - The category to delete.
     */
    public openDeleteCategoryModal(category: any): void {
        const modalRef = this.modalService.open(AddCategoryModalComponent, { size: 'lg' });
        modalRef.componentInstance.mode = 'delete';
        modalRef.componentInstance.categoryData = { ...category };
        modalRef.result.then(
            (result) => {
                if (result === 'deleted') {
                    this.loadCategories();
                }
            }
        );
    }


    /**
     * Navigates back to the previous page in the browser's history.
     */
    goBack(): void {
        this.location.back()
    }

}