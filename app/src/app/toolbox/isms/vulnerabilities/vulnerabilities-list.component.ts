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
import { Component, inject, OnInit, TemplateRef, ViewChild } from '@angular/core';
import { Router } from '@angular/router';
import { finalize } from 'rxjs/operators';
import { NgbModal } from '@ng-bootstrap/ng-bootstrap';

import { ToastService } from 'src/app/layout/toast/toast.service';
import { LoaderService } from 'src/app/core/services/loader.service';
import { CollectionParameters } from 'src/app/services/models/api-parameter';
import { FilterBuilderService } from 'src/app/core/services/filter-builder.service';
import { CoreDeleteConfirmationModalComponent } from 'src/app/core/components/dialog/delete-dialog/core-delete-confirmation-modal.component';



import { Column, Sort, SortDirection } from 'src/app/layout/table/table.types';
import { ExtendableOptionService } from 'src/app/toolbox/isms/services/extendable-option.service';
import { OptionType } from 'src/app/toolbox/isms/models/option-type.enum';
import { ExtendableOption } from 'src/app/framework/models/object-group.model';
import { Vulnerability, VulnerabilityBulkDeleteResult } from '../models/vulnerability.model';
import { VulnerabilityService } from '../services/vulnerability.service';

@Component({
    selector: 'app-vulnerabilities-list',
    templateUrl: './vulnerabilities-list.component.html',
    styleUrls: ['./vulnerabilities-list.component.scss'],
    standalone: false
})
export class VulnerabilitiesListComponent implements OnInit {
    private readonly router = inject(Router);
    private readonly toast = inject(ToastService);
    private readonly loaderService = inject(LoaderService);
    private readonly vulnerabilityService = inject(VulnerabilityService);
    private readonly modalService = inject(NgbModal);
    private readonly filterBuilderService = inject(FilterBuilderService);
    private readonly extendableOptionService = inject(ExtendableOptionService);

    @ViewChild('actionTemplate', { static: true }) actionTemplate: TemplateRef<any>;
    @ViewChild('sourceTemplate', { static: true }) sourceTemplate: TemplateRef<any>;

    public threats: Vulnerability[] = [];
    public totalThreats = 0;

    // Vulnerabilities currently selected in the table for bulk actions
    public selectedVulnerabilities: Vulnerability[] = [];

    public page = 1;
    public limit = 10;
    public loading = false;
    public filter = '';
    public sort: Sort = { name: 'public_id', order: SortDirection.DESCENDING };

    // Table columns
    public columns: Column[] = [];
    public initialVisibleColumns: string[] = [];

    // For showing source names
    public sourceOptions: ExtendableOption[] = [];

    /* --------------------------------------------------- LIFECYCLE MEHTODS --------------------------------------------------- */

    ngOnInit(): void {
        this.setupColumns();
        this.loadSourceOptions();
        this.loadThreats();
    }

    /* --------------------------------------------------- INIT --------------------------------------------------- */

    /* 
    * Define table columns and templates
    */
    setupColumns(): void {
        this.columns = [
            {
                display: 'Public ID',
                name: 'public_id',
                data: 'public_id',
                searchable: false,
                sortable: true,
                style: { width: '120px', 'text-align': 'center' }
            },
            {
                display: 'Name',
                name: 'name',
                data: 'name',
                searchable: true,
                sortable: true,
                style: { width: 'auto'},
                cssClasses: ['text-center'],
            },
            {
                display: 'Identifier',
                name: 'identifier',
                data: 'identifier',
                searchable: true,
                sortable: true,
                style: { width: '180px', 'text-align': 'center' }
            },
            {
                display: 'Source',
                name: 'source',
                data: 'source',
                searchable: true,
                sortable: false,
                template: this.sourceTemplate,
                style: { width: 'auto'},
                cssClasses: ['text-center'],
            },
            {
                display: 'Actions',
                name: 'actions',
                data: 'public_id',
                searchable: false,
                sortable: false,
                fixed: true,
                template: this.actionTemplate,
                style: { width: '80px', 'text-align': 'center' }
            }
        ];
        this.initialVisibleColumns = this.columns.map(c => c.name);
    }


    /* --------------------------------------------------- API CALLS --------------------------------------------------- */

    /*
    * Load the source options
    */
    loadSourceOptions(): void {
        this.loaderService.show();
        this.extendableOptionService.getExtendableOptionsByType(OptionType.THREAT_VULNERABILITY)
            .pipe(finalize(() => this.loaderService.hide()))
            .subscribe({
                next: (res) => {
                    this.sourceOptions = res.results;
                },
                error: (err) => this.toast.error(err?.error?.message)
            });
    }

    /*
    * Load the threats from the backend
    */
    loadThreats(): void {
        this.loading = true;
        this.loaderService.show();

        const filterQuery = this.filterBuilderService.buildFilter(
            this.filter,
            [{ name: 'public_id' }, { name: 'name' }, { name: 'identifier' }]
        );

        const params: CollectionParameters = {
            filter: filterQuery,
            limit: this.limit,
            page: this.page,
            sort: this.sort.name,
            order: this.sort.order
        };

        this.vulnerabilityService.getVulnerabilities(params)
            .pipe(finalize(() => {
                this.loading = false;
                this.loaderService.hide();
            }))
            .subscribe({
                next: (resp) => {
                    this.threats = resp.results;
                    this.totalThreats = resp.total;
                },
                error: (err) => {
                    this.toast.error(err?.error?.message);
                }
            });
    }

    /* --------------------------------------------------- ACTIONS--------------------------------------------------- */

    /*
    * Add a new Vulnerability
    */
    onAddNew(): void {
        this.router.navigate(['/isms/vulnerabilities/add']);
    }

    /*
    * Edit a vulnerability
    */

    public onEdit(vulnerability: Vulnerability): void {
        // Directly pass the entire object in router state
        this.router.navigate(
            ['/isms/vulnerabilities/edit'],
            { state: { vulnerability } }
        );
    }


    /*
    * View a vulnerability
    */
    public onView(vulnerability: Vulnerability): void {
        this.router.navigate(
          ['/isms/vulnerabilities/view'],
          { state: { vulnerability } }
        );
      }
      


    /*
    * Delete a vulnerability
    */
    onDelete(vulnerability: Vulnerability): void {
        const modalRef = this.modalService.open(CoreDeleteConfirmationModalComponent, {
            size: 'lg',
            windowClass: 'dg-modal-window',
            backdropClass: 'dg-modal-window-backdrop'
        });
        modalRef.componentInstance.title = 'Delete Vulnerability';
        modalRef.componentInstance.item = vulnerability;
        modalRef.componentInstance.itemType = 'Vulnerability';
        modalRef.componentInstance.itemName = vulnerability.name;

        modalRef.result.then(
            (result) => {
                if (result === 'confirmed' && vulnerability.public_id) {
                    this.loaderService.show();
                    this.vulnerabilityService.deleteVulnerability(vulnerability.public_id)
                        .pipe(finalize(() => this.loaderService.hide()))
                        .subscribe({
                            next: () => {
                                this.toast.success('Vulnerability deleted successfully.');
                                this.loadThreats();
                            },
                            error: (err) => {
                                this.toast.error(err?.error?.message);
                            }
                        });
                }
            },
            () => { }
        );
    }


    /*
    * Keep track of the vulnerabilities selected in the table.
    */
    public onSelectedChange(selected: Vulnerability[]): void {
        this.selectedVulnerabilities = selected ?? [];
    }


    /*
    * Delete all currently selected vulnerabilities. Vulnerabilities that are
    * still assigned to a Risk are reported back as skipped.
    */
    public onDeleteSelected(): void {
        const publicIds = this.selectedVulnerabilities
            .map((vulnerability) => vulnerability.public_id)
            .filter((id): id is number => id != null);

        if (!publicIds.length) {
            return;
        }

        const isPlural = publicIds.length > 1;
        const modalRef = this.modalService.open(CoreDeleteConfirmationModalComponent, {
            size: 'lg',
            windowClass: 'dg-modal-window',
            backdropClass: 'dg-modal-window-backdrop'
        });
        modalRef.componentInstance.title = 'Delete Vulnerabilities';
        modalRef.componentInstance.item = this.selectedVulnerabilities;
        modalRef.componentInstance.itemType = 'Vulnerabilities';
        modalRef.componentInstance.itemName = `${publicIds.length} selected Vulnerabilit${isPlural ? 'ies' : 'y'}`;
        modalRef.componentInstance.warningMessage =
            'Vulnerabilities assigned to a Risk cannot be deleted and will be skipped.';

        modalRef.result.then(
            (result) => {
                if (result !== 'confirmed') {
                    return;
                }
                this.loaderService.show();
                this.vulnerabilityService.deleteVulnerabilities(publicIds)
                    .pipe(finalize(() => this.loaderService.hide()))
                    .subscribe({
                        next: (response) => {
                            this.notifyBulkDeleteResult(response);
                            this.selectedVulnerabilities = [];
                            this.loadThreats();
                        },
                        error: (err) => {
                            this.toast.error(err?.error?.message);
                        }
                    });
            },
            () => { }
        );
    }


    /* --------------------------------------------------- Pagination, sorting, and search handlers --------------------------------------------------- */


    onPageChange(page: number): void {
        this.selectedVulnerabilities = [];
        this.page = page;
        this.loadThreats();
    }

    onPageSizeChange(limit: number): void {
        this.selectedVulnerabilities = [];
        this.limit = limit;
        this.page = 1;
        this.loadThreats();
    }

    onSortChange(sort: Sort): void {
        this.selectedVulnerabilities = [];
        this.sort = sort;
        this.loadThreats();
    }

    onSearchChange(search: string): void {
        this.selectedVulnerabilities = [];
        this.filter = search;
        this.page = 1;
        this.loadThreats();
    }

    /*
  * Get the source name by its public_id
  */
    getSourceNames(sourceIds: number): string {
        const option = this.sourceOptions.find(opt => opt.public_id === sourceIds);
        return option?.value;
    }

    /* --------------------------------------------------- PRIVATE FUNCTIONS --------------------------------------------------- */

    /*
    * Surface the outcome of a bulk delete: how many vulnerabilities were removed
    * and which ones were skipped because they are still assigned to a Risk.
    */
    private notifyBulkDeleteResult(result: VulnerabilityBulkDeleteResult): void {
        const deletedCount = result?.successfully?.length ?? 0;
        const inUseIds = result?.in_use ?? [];

        if (deletedCount > 0) {
            this.toast.success(`${deletedCount} Vulnerabilit${deletedCount > 1 ? 'ies' : 'y'} deleted successfully.`);
        }

        if (inUseIds.length) {
            const names = inUseIds.map((id) => this.getVulnerabilityName(id)).join(', ');
            const isPlural = inUseIds.length > 1;
            this.toast.warning(
                `${inUseIds.length} Vulnerabilit${isPlural ? 'ies' : 'y'} could not be deleted because ` +
                `${isPlural ? 'they are' : 'it is'} assigned to a Risk: ${names}.`
            );
        }
    }


    /*
    * Resolve a vulnerability's display name by its public id, falling back to the id.
    */
    private getVulnerabilityName(publicId: number): string {
        const vulnerability = this.threats.find((item) => item.public_id === publicId);
        return vulnerability?.name ?? `#${publicId}`;
    }
}
