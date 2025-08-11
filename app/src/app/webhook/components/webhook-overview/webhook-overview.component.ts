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
import { WebhookService } from '../../services/webhook.service';
import { Webhook } from '../../models/webhook.model';
import { Router } from '@angular/router';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { NgbModal } from '@ng-bootstrap/ng-bootstrap';
import { DeleteConfirmationModalComponent } from '../modal/delete-confirmation-modal.component';
import { LoaderService } from 'src/app/core/services/loader.service';
import { finalize } from 'rxjs';

@Component({
    selector: 'app-webhook-overview',
    templateUrl: './webhook-overview.component.html',
    styleUrls: ['./webhook-overview.component.scss'],
    standalone: false
})
export class WebhookOverviewComponent implements OnInit {
    public webhooks: Webhook[] = [];
    public totalWebhooks: number = 0;
    public page: number = 1;
    public limit: number = 10;
    public loading = false;

    @ViewChild('actionsTemplate', { static: true }) actionsTemplate: TemplateRef<any>; // Reference the actions template
    @ViewChild('statusTemplate', { static: true }) statusTemplate: TemplateRef<any>; // Reference the template


    public columns: Array<any>;
    public isLoading$ = this.loaderService.isLoading$;

    /* --------------------------------------------------- LIFECYCLE METHODS -------------------------------------------------- */

    constructor(private webhookService: WebhookService,
        private router: Router,
        private toast: ToastService,
        private modalService: NgbModal,
         private loaderService: LoaderService
    ) { }

    ngOnInit(): void {
        this.columns = [
            { display: 'ID', name: 'public_id_str', data: 'public_id', searchable: true, sortable: true, style: { width: '80px', 'text-align': 'center' } },
            { display: 'Name', name: 'name', data: 'name', sortable: true },
            { display: 'URL', name: 'url', data: 'url', sortable: true },
            { display: 'Status', name: 'active', data: 'active', sortable: false, template: this.statusTemplate, style: { width: '140px', 'text-align': 'center' } },
            { display: 'Actions', name: 'actions', template: this.actionsTemplate, sortable: false, style: { width: '80px', 'text-align': 'center' } },
        ];

        this.loadWebhooks();
    }

    /* --------------------------------------------------- API METHODS -------------------------------------------------- */

    /**
     * Loads all webhooks with the current pagination settings.
     * Sets the loading state, retrieves webhooks from the service, and updates component state.
     */
    private loadWebhooks(): void {
        this.loading = true;
        this.loaderService.show();

        this.webhookService.getAllWebhooks({
            filter: '',
            limit: this.limit,
            page: this.page,
            sort: 'name',
            order: 1,
        }).pipe(finalize(() => this.loaderService.hide())).subscribe({
            next: (data) => {
                this.webhooks = data.results;
                this.totalWebhooks = data.total;
            },
            error: (error) => {
                this.webhooks = [];
                this.totalWebhooks = 0;
                this.toast.error(error?.error?.message)
            },
            complete: () => (this.loading = false),
        });
    }

    /* --------------------------------------------------- ACTIONS -------------------------------------------------- */


    /**
     * Navigates to the edit page for the specified webhook.
     * @param publicId - The public ID of the webhook to edit.
     */
    public editWebhook(publicId: number): void {
        this.router.navigate([`/webhooks/edit`, publicId]);
    }


    /**
     * Initiates the deletion process for the specified webhook.
     * @param publicId - The public ID of the webhook to delete.
     */
    public deleteWebhook(publicId: number): void {
        this.loaderService.show();

        this.webhookService.deleteWebhook(publicId).pipe(finalize(() => this.loaderService.hide())).subscribe({
            next: (res) => {
                this.toast.success('Webhook deleted Sucessfully')
                this.loadWebhooks()
            },
            error: (err) => {
                this.toast.error(err?.error?.message)
            }
        })
    }


    /**
     * Handles the page change event for pagination and reloads webhooks.
     * @param newPage - The new page number to load.
     */
    public onPageChange(newPage: number): void {
        this.page = newPage;
        this.loadWebhooks();
    }


    /**
     * Handles the change in page size, resets to the first page, and reloads webhooks.
     * @param newLimit - The new number of items per page.
     */
    public onPageSizeChange(newLimit: number): void {
        this.limit = newLimit;
        this.page = 1;
        this.loadWebhooks();
    }

    /**
     * Opens the Delete Report modal and deletes the report if confirmed.
     * @param report - The report to delete.
     */
    public onDeleteWebhook(webhook: any): void {
        this.openDeleteModal(
            webhook,
            `Delete Webhook: ${webhook.name}`,
            `Do you want to delete the webhook "${webhook.name}"? This action cannot be undone.`
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
        modalRef.componentInstance.itemType = 'Webhook';
        modalRef.componentInstance.itemName = item.name;

        modalRef.result.then(
            (result) => {
                if (result === 'confirmed') {
                    this.deleteWebhook(item.public_id);
                }
            },
            () => { }
        );
    }
}