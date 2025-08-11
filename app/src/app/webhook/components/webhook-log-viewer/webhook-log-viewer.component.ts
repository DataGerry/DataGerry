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
import { Component, OnInit, TemplateRef, ViewChild } from '@angular/core';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { WebhookLogService } from '../../services/webhookLog.service';
import { DeleteConfirmationModalComponent } from '../modal/delete-confirmation-modal.component';
import { NgbModal } from '@ng-bootstrap/ng-bootstrap';
import { Sort, SortDirection } from 'src/app/layout/table/table.types';
import { finalize, ReplaySubject, takeUntil } from 'rxjs';
import { CollectionParameters } from 'src/app/services/models/api-parameter';
import { APIGetMultiResponse } from 'src/app/services/models/api-response';
import { Location } from '@angular/common';
import { LoaderService } from 'src/app/core/services/loader.service';

@Component({
    selector: 'app-webhook-log-viewer',
    templateUrl: './webhook-log-viewer.component.html',
    styleUrls: ['./webhook-log-viewer.component.scss'],
    standalone: false
})
export class WebhookLogViewerComponent implements OnInit {
    public logs: any[] = [];
    public loading = false;
    public datePlaceholder = 'YYYY-MM-DD';
    public columns: any[];
    public totalLogs: number = 0;
    public limit: number = 10;
    public page: number = 1;
    public sort: Sort = { name: 'webhook_id', order: SortDirection.ASCENDING } as Sort;
    public filter: string;
    public isLoading$ = this.loaderService.isLoading$;

    private unsubscribe$ = new ReplaySubject<void>(1);


    @ViewChild('actionsTemplate', { static: true }) actionsTemplate: TemplateRef<any>;


    constructor(
        private webhookService: WebhookLogService,
        private toast: ToastService, 
        private modalService: NgbModal, 
        private location: Location,
        private loaderService: LoaderService) { }

    ngOnInit(): void {
        this.columns = [
            { display: 'Webhook ID', name: 'webhook_id', data: 'webhook_id', searchable: true, sortable: true, style: { width: '30px', 'text-align': 'center' } },
            { display: 'Date', data: 'event_time', style: { 'text-align': 'center' } },
            { display: 'Status', data: 'status', style: { 'text-align': 'center' } },
            { display: 'Response Code', data: 'response_code', style: { width: '140px', 'text-align': 'center' } },
            { display: 'Actions', name: 'actions', template: this.actionsTemplate, sortable: false, style: { width: '80px', 'text-align': 'center' } }
        ];
        this.loadLogs();
    }


    /**
     * Loads logs by retrieving all webhooks and formatting the event time and status for each log.
     * Sets the loading state and handles errors gracefully.
     */
    private loadLogs(): void {
        this.loading = true;
        this.loaderService.show();

        const params: CollectionParameters = {
            filter: this.filterBuilder(),
            limit: this.limit,
            page: this.page,
            sort: this.sort.name.replace('_str', ''),
            order: this.sort.order,
        };

        this.webhookService
            .getAllWebhooks(params)
            .pipe(takeUntil(this.unsubscribe$), finalize(() => this.loaderService.hide()))
            .subscribe({
                next: (response: APIGetMultiResponse<any>) => {
                    if (response && response.results) {
                        this.logs = response.results.map((log) => ({
                            ...log,
                            event_time: this.formatEventDate(log.event_time),
                            status: log.status ? 'Active' : 'Inactive',
                        }));
                        this.totalLogs = response.total || 0;
                    } else {
                        this.logs = [];
                        this.totalLogs = 0;
                    }
                    this.loading = false;
                },
                error: (err) => {
                    this.toast.error(err?.error?.message);
                    this.logs = [];
                    this.totalLogs = 0;
                    this.loading = false;
                },
            });
    }



    /**
     * Formats the event time from a raw date object to a localized date string.
     * @param eventTime - The raw event time object to format.
     * @returns A formatted date string or a placeholder if the date is invalid.
     */
    private formatEventDate(eventTime: any): string {
        if (eventTime?.$date) {
            return new Date(eventTime.$date).toLocaleDateString('en-US');
        }
        return this.datePlaceholder;
    }


    /**
 * Initiates the deletion process for the specified webhook.
 * @param publicId - The public ID of the webhook to delete.
 */
    public deleteLog(publicId: number): void {
        this.loaderService.show();
        this.webhookService.deleteWebhookLog(publicId).pipe(finalize(() => this.loaderService.hide())).subscribe({
            next: (res) => {
                this.toast.success('Webhook deleted Sucessfully');
                this.loadLogs();
            },
            error: (err) => {
                this.toast.error(err?.error?.message)
            }
        })
    }

    /**
    * Opens the Delete Report modal and deletes the report if confirmed.
    * @param report - The report to delete.
    */
    public onDeleteLog(log: any): void {
        this.openDeleteModal(
            log,
            `Delete Log: ID: ${log.webhook_id}`,
            `Do you want to delete the log "${log.webhook_id}"? This action cannot be undone.`
        );
    }


    /**
     * Opens a delete confirmation modal for the specified item.
     * Passes the item details and a descriptive title to the modal, and deletes the item upon confirmation.
     * @param item - The item to be deleted.
     * @param title - The title to display in the modal.
     * @param description - The description to display in the modal (currently unused in the code).
     */
    public openDeleteModal(item: any, title: string, description: string): void {
        const modalRef = this.modalService.open(DeleteConfirmationModalComponent, { size: 'lg' });
        modalRef.componentInstance.title = title;
        modalRef.componentInstance.item = item;
        modalRef.componentInstance.itemType = 'log';
        modalRef.componentInstance.itemName = item.webhook_id;

        modalRef.result.then(
            (result) => {
                if (result === 'confirmed') {
                    this.deleteLog(item.public_id);
                }
            },
            () => { }
        );
    }


    /* --------------------------------------------------- Pagination, Sorting, and Search Handlers -------------------------------------------------- */


    /**
     * Handles changes to the current page in pagination and reloads the logs.
     * @param newPage - The new page number to display.
     */
    public onPageChange(newPage: number): void {
        this.page = newPage;
        this.loadLogs();
    }


    /**
     * Handles changes to the number of items displayed per page, resets to the first page, and reloads the logs.
     * @param limit - The new number of items per page.
     */
    public onPageSizeChange(limit: number): void {
        this.limit = limit;
        this.page = 1;
        this.loadLogs();
    }


    /**
     * Handles changes to the sorting criteria and reloads the logs.
     * @param sort - The new sort criteria.
     */
    public onSortChange(sort: Sort): void {
        this.sort = sort;
        this.loadLogs();
    }


    /**
     * Handles changes to the search input, updates the filter, resets to the first page, and reloads the logs.
     * @param search - The search query string.
     */
    public onSearchChange(search: string): void {
        this.filter = search || undefined;
        this.page = 1;
        this.loadLogs();
    }


    /**
     * Builds the filter query for searching.
     */
    private filterBuilder(): any[] {
        const query: any[] = [];

        if (this.filter) {
            const searchableColumns = this.columns.filter((c) => c.searchable);
            const orConditions: any[] = [];
            const addFields: any = {};

            for (const column of searchableColumns) {
                let fieldName = column.data || column.name;
                let searchField = fieldName;

                // Handle numeric and date fields by converting them to strings
                if (fieldName === 'webhook_id') {
                    addFields['webhook_id_str'] = { $toString: '$webhook_id' };
                    searchField = 'webhook_id_str';
                }

                if (fieldName === 'response_code') {
                    addFields['response_code_str'] = { $toString: '$response_code' };
                    searchField = 'response_code_str';
                }

                if (fieldName === 'event_time') {
                    addFields['event_time_str'] = {
                        $dateToString: { format: '%Y-%m-%d', date: '$event_time' },
                    };
                    searchField = 'event_time_str';
                }

                // Add regex condition
                const regexCondition: any = {};
                regexCondition[searchField] = {
                    $regex: String(this.filter),
                    $options: 'i',
                };
                orConditions.push(regexCondition);
            }

            if (Object.keys(addFields).length > 0) {
                query.push({ $addFields: addFields });
            }

            query.push({
                $match: {
                    $or: orConditions,
                },
            });
        }

        return query;
    }

    /**
     * Navigates back to the previous page in the browser's history.
     */
    goBack(): void {
        this.location.back()
    }
}