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
import { DatePipe } from '@angular/common';

import { ReplaySubject, takeUntil } from 'rxjs';

import { NgbModalRef } from '@ng-bootstrap/ng-bootstrap/modal/modal-ref';
import { NgbModal } from '@ng-bootstrap/ng-bootstrap';

import { LinkService } from '../../../services/link.service';
import { ToastService } from '../../../../layout/toast/toast.service';

import { CollectionParameters } from '../../../../services/models/api-parameter';
import { Column, Sort, SortDirection } from '../../../../layout/table/table.types';
import { CmdbLink } from '../../../models/cmdb-link';
import { APIGetMultiResponse } from '../../../../services/models/api-response';
import { AccessControlList } from 'src/app/modules/acl/acl.types';
import { ObjectLinkAddModalComponent } from '../../modals/object-link-add-modal/object-link-add-modal.component';
import { RenderResult } from '../../../models/cmdb-render';
import { ObjectLinkDeleteModalComponent } from '../../modals/object-link-delete-modal/object-link-delete-modal.component';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'cmdb-object-links-table',
    templateUrl: './object-links-table.component.html',
    styleUrls: ['./object-links-table.component.scss'],
    standalone: false
})
export class ObjectLinksTableComponent implements OnInit, OnDestroy {

    private subscriber: ReplaySubject<void> = new ReplaySubject<void>();

    // Table Template: Link partner column
    @ViewChild('partnerTemplate', { static: true }) partnerTemplate: TemplateRef<any>;

    // Table Template: Link action column
    @ViewChild('actionTemplate', { static: true }) actionTemplate: TemplateRef<any>;

    // Table Custom Template: Link add button
    @ViewChild('addButtonTemplate', { static: true }) addButtonTemplate: TemplateRef<any>;

    public objectID: number;
    public object: RenderResult;

    @Input('object')
    public set Object(obj: RenderResult) {
        this.objectID = obj.object_information.object_id;
        this.object = obj;
        this.loadLinksFromAPI();
    }

    @Input() public acl: AccessControlList;

    private modalRef: NgbModalRef;

    // Table columns definition
    public columns: Array<Column>;

    public links: Array<CmdbLink> = [];
    public linksAPIResponse: APIGetMultiResponse<CmdbLink>;
    public totalLinks: number = 0;

    // Max number of objects per site
    public limit: number = 10;

    // Begin with first page
    public page: number = 1;

    public sort: Sort = { name: 'public_id', order: SortDirection.DESCENDING } as Sort;

    public loading: boolean = false;

/* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */
    constructor(private linkService: LinkService,
                private modalService: NgbModal,
                private toast: ToastService) {

    }


    public ngOnInit() {
        this.columns = [
            {
                display: 'Public ID',
                name: 'public_id',
                data: 'public_id',
                sortable: true
            },
            {
                display: 'Linked object',
                name: 'partner',
                template: this.partnerTemplate,
                sortable: false,
            },
            {
                display: 'Creation Time',
                name: 'creation_time',
                data: 'creation_time',
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
                template: this.actionTemplate,
                sortable: false,
                fixed: true,
                cssClasses: ['text-center'],
                cellClasses: ['actions-buttons'],
                style: { width: '6rem' }
            },
        ] as Array<Column>;
    }


    public ngOnDestroy(): void {
        if (this.modalRef) {
            this.modalRef.close();
        }

        this.subscriber?.next();
        this.subscriber?.complete();
    }

/* ------------------------------------------------- HELPER METHODS ------------------------------------------------- */

    /**
     * On table sort change reload all links
     */
    public onSortChange(sort: Sort): void {
        this.sort = sort;
        this.loadLinksFromAPI();
    }


    /**
     * On table page change Reload all links
     */
    public onPageChange(page: number) {
        this.page = page;
        this.loadLinksFromAPI();
    }


    /**
     * On table page size change Reload all links
     */
    public onPageSizeChange(limit: number): void {
        this.limit = limit;
        this.loadLinksFromAPI();
    }


    /**
     * Load/reload links from the API
     */
    private loadLinksFromAPI(): void {
        this.loading = true;

        const params: CollectionParameters = {
            filter: undefined,
            limit: this.limit,
            sort: this.sort.name,
            order: this.sort.order,
            page: this.page
        };

        this.linkService.getPartnerLinks(this.objectID, params).pipe(takeUntil(this.subscriber))
        .subscribe((apiResponse: APIGetMultiResponse<CmdbLink>) => {
            this.linksAPIResponse = apiResponse;
            this.links = apiResponse.results as Array<CmdbLink>;
            this.totalLinks = apiResponse.total;
            this.loading = false;
        });
    }

/* ------------------------------------------------- MODALS SECTION ------------------------------------------------- */

    public onShowAddModal(): void {
        this.modalRef = this.modalService.open(ObjectLinkAddModalComponent);
        this.modalRef.componentInstance.primaryRenderResult = this.object;

        this.modalRef.result.then(
            (formData: any) => {
                if (formData) {
                    // console.log("formData: ", formData);
                    // delete formData['primary']
                    // return;
                    this.linkService.postLink(formData).pipe(takeUntil(this.subscriber))
                    .subscribe({
                        next: () => {
                            this.toast.success(`Object #${formData.primary} linked with #${formData.secondary}.`);
                            this.loadLinksFromAPI();
                        },
                        error: (error) => {
                            this.toast.error(`${error.error}`);
                        }
                    });
                } 
            },
            (reason: any) => {
                // Handle modal dismissal rejection
            }
        );
    }


    public onShowDeleteModal(link: CmdbLink): void {
        this.modalRef = this.modalService.open(ObjectLinkDeleteModalComponent);
        this.modalRef.componentInstance.publicID = link.public_id;

        this.modalRef.componentInstance.closeEmitter.pipe(takeUntil(this.subscriber))
        .subscribe((closeResponse: string) => {
            if (closeResponse === 'deleted') {
                this.loadLinksFromAPI();
            }
        });
    }
}