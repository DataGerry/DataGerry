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
import { Component, OnInit, OnDestroy, ViewChild, TemplateRef } from '@angular/core';

import { finalize, ReplaySubject, takeUntil } from 'rxjs';

import { NgbModal } from '@ng-bootstrap/ng-bootstrap';
import { NgbModalRef } from '@ng-bootstrap/ng-bootstrap/modal/modal-ref';

import { DocapiService } from '../../services/docapi.service';

import { DocTemplate } from '../../models/cmdb-doctemplate';
import { APIGetMultiResponse } from '../../../../services/models/api-response';
import { Column, Sort, SortDirection } from '../../../../layout/table/table.types';
import { CollectionParameters } from '../../../../services/models/api-parameter';
import { GeneralModalComponent } from '../../../../layout/helpers/modals/general-modal/general-modal.component';
import { LoaderService } from 'src/app/core/services/loader.service';
import { ToastService } from 'src/app/layout/toast/toast.service';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'cmdb-docapi-template-list',
    templateUrl: './docapi-list.component.html',
    styleUrls: ['./docapi-list.component.scss'],
    standalone: false
})
export class DocapiListComponent implements OnInit, OnDestroy {

    public subscriber: ReplaySubject<void> = new ReplaySubject<void>();
    public messageBlock: string = 'Document Generator is an interface for generating PDF documents out of CMDB data. A user can design a\n' +
        'Document Template in the frontend. Each Document Template consists of a Template Type, Template\n' +
        'Content and Template Styling. The Template Type defines the kind of the template. For example the Object Template type\n' +
        'generates documents for single CMDB objects. Each Template Type may have its own configuration settings. For Object\n' +
        'Templates, an object type needs to be configured. In the Template Content section, the document itself can be designed\n' +
        ' with an WYSIWYG editor. Depending on the chosen Template Type, template variables can be used at all places of the\n' +
        ' document. These variables will then be replaced when rendering the document for a specific object.'


    // Table Template: actions column
    @ViewChild('actionsTemplate', { static: true }) actionsTemplate: TemplateRef<any>;

    // Table Template: add button
    @ViewChild('addButton', { static: true }) addButton: TemplateRef<any>;

    private modalRef: NgbModalRef;

    // Current template collection
    public templates: Array<DocTemplate> = [];
    public templateAPIResponse: APIGetMultiResponse<DocTemplate>;
    public totalTemplates: number = 0;

    public columns: Array<Column>;

    // Table selection enabled
    public selectEnabled: boolean = false;

    // Begin with first page
    public page: number = 1;

    // Max number of types per site
    public limit: number = 10;

    // Filter query from the table search input
    public filter: string;

    // Default sort filter
    public sort: Sort = { name: 'public_id', order: SortDirection.DESCENDING } as Sort;

    public loading: boolean = false;
    public isLoading$ = this.loaderService.isLoading$;

/* ------------------------------------------------------------------------------------------------------------------ */
/*                                                     LIFE CYCLE                                                     */
/* ------------------------------------------------------------------------------------------------------------------ */
    constructor(
        private docapiService: DocapiService, 
        private modalService: NgbModal,
        private loaderService: LoaderService,
        private toast: ToastService) {

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
                display: 'Label',
                name: 'label',
                data: 'label',
                searchable: true,
                sortable: true
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
            }
        ] as Array<Column>;

        this.loadTemplatesFromAPI();
    }


    public ngOnDestroy(): void {
        this.subscriber?.next();
        this.subscriber?.complete();

        if (this.modalRef) {
            this.modalRef?.close();
        }
    }

/* ------------------------------------------------- HELPER METHODS ------------------------------------------------- */

    /**
     * Load/reload types from the api
     */
    private loadTemplatesFromAPI(): void {
        this.loaderService?.show();
        this.loading = true;
        let query;

        if (this.filter) {
            query = [];
            const or = [];
            const searchableColumns = this.columns?.filter(c => c?.searchable);

            // Searchable Columns
            for (const column of searchableColumns) {
                const regex: any = {};
                regex[column?.name] = {
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

        this.docapiService.getDocTemplateList(params).pipe(takeUntil(this.subscriber), finalize(() =>  this.loaderService?.hide())).subscribe(
            (apiResponse: APIGetMultiResponse<DocTemplate>) => {
                this.templateAPIResponse = apiResponse;
                this.templates = apiResponse?.results as Array<DocTemplate>;
                this.totalTemplates = apiResponse?.total;
                this.loading = false;
            }
        );
    }


    public delDocTemplate(publicId: number): void {
        this.modalRef = this.modalService.open(GeneralModalComponent);
        this.modalRef.componentInstance.title = 'Delete Document Template';
        this.modalRef.componentInstance.modalMessage = 'Are you sure you want to delete this Document Template?';
        this.modalRef.componentInstance.buttonDeny = 'Cancel';
        this.modalRef.componentInstance.buttonAccept = 'Delete';

        this.modalRef.result.then((result) => {
            if (result) {
                this.loaderService?.show();
                this.docapiService?.deleteDocTemplate(publicId)?.pipe(finalize(() => this.loaderService?.hide())).subscribe({
                    next: resp => {},
                    error: error => this.toast.error('An error occurred while deleting the Document Template'),
                    complete: () => this.loadTemplatesFromAPI()
                });
            }
        });
    }


    /**
     * On table sort change reload all types
     *
     * @param sort
     */
    public onSortChange(sort: Sort): void {
        this.sort = sort;
        this.loadTemplatesFromAPI();
    }


    /**
     * On table page change reload all templates
     *
     * @param page
     */
    public onPageChange(page: number) {
        this.page = page;
        this.loadTemplatesFromAPI();
    }


    /**
     * On table page size change reload all templates
     *
     * @param limit
     */
    public onPageSizeChange(limit: number): void {
        this.limit = limit;
        this.loadTemplatesFromAPI();
    }


    /**
     * On table search change reload all templates
     *
     * @param search
     */
    public onSearchChange(search: any): void {
        if (search) {
            this.filter = search;
        } else {
            this.filter = undefined;
        }

        this.loadTemplatesFromAPI();
    }
}
