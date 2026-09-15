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
import {
    Component,
    inject,
    OnInit,
    TemplateRef,
    ViewChild,
} from '@angular/core';
import { Router } from '@angular/router';
import { NgbModal } from '@ng-bootstrap/ng-bootstrap';
import { finalize } from 'rxjs/operators';

import { ToastService } from 'src/app/layout/toast/toast.service';
import { LoaderService } from 'src/app/core/services/loader.service';
import { FilterBuilderService } from 'src/app/core/services/filter-builder.service';
import { CoreDeleteConfirmationModalComponent } from 'src/app/core/components/dialog/delete-dialog/core-delete-confirmation-modal.component';


import { CollectionParameters } from 'src/app/services/models/api-parameter';
import { Column, Sort, SortDirection } from 'src/app/layout/table/table.types';
import { ControlMeasure, ControlMeasureBulkDeleteResult } from '../../models/control-measure.model';
import { ControlMeasureService } from '../../services/control-measure.service';
import { OptionType } from '../../models/option-type.enum';
import { ExtendableOptionService } from '../../services/extendable-option.service';
import { ExtendableOption } from 'src/app/framework/models/object-group.model';
import { state } from '@angular/animations';
@Component({
    selector: 'app-control-measures-list',
    templateUrl: './control-measures-list.component.html',
    styleUrls: ['./control-measures-list.component.scss'],
    standalone: false
})
export class ControlmeasuresListComponent implements OnInit {
    @ViewChild('actionTemplate', { static: true }) actionTemplate: TemplateRef<any>;
    @ViewChild('sourceTemplate', { static: true }) sourceTemplate: TemplateRef<any>;
    @ViewChild('implementationStateTemplate', { static: true }) implementationStateTemplate: TemplateRef<any>;

    public controlMeasures: ControlMeasure[] = [];
    public totalControlMeasures = 0;

    // Controls currently selected in the table for bulk actions
    public selectedControls: ControlMeasure[] = [];

    // Table config
    public page = 1;
    public limit = 10;
    public loading = false;
    public filter = '';
    public sort: Sort = { name: 'public_id', order: SortDirection.DESCENDING };
    public columns: Column[] = [];
    public initialVisibleColumns: string[] = [];

    // For showing source names
    public sourceOptions: ExtendableOption[] = [];
    public implementationStateOptions: ExtendableOption[] = [];

    private readonly router = inject(Router);
    private readonly toast = inject(ToastService);
    private readonly loaderService = inject(LoaderService);
    private readonly modalService = inject(NgbModal);
    private readonly filterBuilderService = inject(FilterBuilderService);
    private readonly controlmeasureservice = inject(ControlMeasureService);
    private readonly extendableOptionService = inject(ExtendableOptionService);

    ngOnInit(): void {
        this.setupColumns();
        this.loadSourceOptions();
        this.loadImplementationStateOptions(); 
        this.loadControlMeasures();
    }

    /**
     * Define columns for cmdb-table
     */
    private setupColumns(): void {
        this.columns = [
            {
                display: 'Public ID',
                name: 'public_id',
                data: 'public_id',
                searchable: false,
                sortable: true,
                style: { width: '80px', 'text-align': 'center' }
            },
            {
                display: 'Name',
                name: 'title',
                data: 'title',
                searchable: true,
                sortable: true,
                style: { width: '200px' }
            },
            // {
            //     display: 'Type',
            //     name: 'control_measure_type',
            //     data: 'control_measure_type',
            //     searchable: true,
            //     sortable: true,
            //     style: { width: '150px', 'text-align': 'center' }
            // },
            {
                display: 'Identifier',
                name: 'identifier',
                data: 'identifier',
                searchable: true,
                sortable: false,
                style: { width: '150px', 'text-align': 'center' }
            },
            {
                display: 'Implementation State',
                name: 'implementation_state',
                data: 'implementation_state',
                searchable: true,
                sortable: false,
                template: this.implementationStateTemplate, 
                style: { width: '150px', 'text-align': 'center' }
            },
            // {
            //     display: 'Source',
            //     name: 'source',
            //     data: 'source',
            //     searchable: false,
            //     sortable: false,
            //     template: this.sourceTemplate,
            //     style: { width: '100px', 'text-align': 'center' }
            // },
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
        this.initialVisibleColumns = this.columns.map((c) => c.name);
    }

    /**
     * Load data from backend
     */
    private loadControlMeasures(): void {
        this.loading = true;
        this.loaderService.show();

        const filterQuery = this.filterBuilderService.buildFilter(
            this.filter,
            [
                { name: 'title' },
                { name: 'control_measure_type' }
            ]
        );

        const params: CollectionParameters = {
            filter: filterQuery,
            limit: this.limit,
            page: this.page,
            sort: this.sort.name,
            order: this.sort.order
        };

        this.controlmeasureservice.getControlMeasures(params)
            .pipe(finalize(() => {
                this.loading = false;
                this.loaderService.hide();
            }))
            .subscribe({
                next: (resp) => {
                    this.controlMeasures = resp.results;
                    this.totalControlMeasures = resp.total;
                },
                error: (err) => {
                    this.toast.error(err?.error?.message);
                }
            });
    }


    /*
    * Load the source options
    */
    loadSourceOptions(): void {
        this.loaderService.show();
        this.extendableOptionService.getExtendableOptionsByType(OptionType.CONTROL_MEASURE)
            .pipe(finalize(() => this.loaderService.hide()))
            .subscribe({
                next: (res) => {
                    this.sourceOptions = res.results;
                },
                error: (err) => this.toast.error(err?.error?.message)
            });
    }


    /**
     * Navigate to add new control/measure page
     * @returns {void}
     */
    public onAddNew(): void {
        this.router.navigate(['/isms/control-measures/add']);
    }

    /**
     * Navigate to view control/measure page
     * @param item - The control/measure to view
     * @returns {void}
     */
    public onView(item: ControlMeasure): void {
        this.router.navigate(['/isms/control-measures/view'], { state: { controlMeasure: item, mode: 'view' } });
    }


    /**
     * Navigate to edit control/measure page
     * @param item - The control/measure to edit
     * @returns {void}
     */
    public onEdit(item: ControlMeasure): void {
        this.router.navigate(['/isms/control-measures/edit'], { state: { controlMeasure: item } });
    }


    /**
     * Delete control/measure
     * @param item - The control/measure to delete
     * @returns {void}
     */
    public onDelete(item: ControlMeasure): void {
        if (!item.public_id) {
            return;
        }
        const modalRef = this.modalService.open(CoreDeleteConfirmationModalComponent, {
            size: 'lg',
            windowClass: 'dg-modal-window',
            backdropClass: 'dg-modal-window-backdrop'
        });
        modalRef.componentInstance.title = 'Delete Control';
        modalRef.componentInstance.item = item;
        modalRef.componentInstance.itemType = 'Control';
        modalRef.componentInstance.itemName = item.title;

        modalRef.result.then(
            (result) => {
                if (result === 'confirmed') {
                    this.loaderService.show();
                    this.controlmeasureservice.deleteControlMeasure(item.public_id)
                        .pipe(finalize(() => this.loaderService.hide()))
                        .subscribe({
                            next: () => {
                                this.toast.success('Control deleted successfully.');
                                this.loadControlMeasures();
                            },
                            error: (err) => {
                                this.toast.error(err?.error?.message);
                            }
                        });
                }
            },
            () => { /* dismissed */ }
        );
    }


    /**
     * Keep track of the controls selected in the table.
     * @param selected - The currently selected controls
     * @returns {void}
     */
    public onSelectedChange(selected: ControlMeasure[]): void {
        this.selectedControls = selected ?? [];
    }


    /**
     * Delete all currently selected controls. Controls assigned to a control
     * measure assignment (CMA) are reported back as skipped.
     * @returns {void}
     */
    public onDeleteSelected(): void {
        const publicIds = this.selectedControls
            .map((control) => control.public_id)
            .filter((id): id is number => id != null);

        if (!publicIds.length) {
            return;
        }

        const modalRef = this.modalService.open(CoreDeleteConfirmationModalComponent, {
            size: 'lg',
            windowClass: 'dg-modal-window',
            backdropClass: 'dg-modal-window-backdrop'
        });
        modalRef.componentInstance.title = 'Delete Controls';
        modalRef.componentInstance.item = this.selectedControls;
        modalRef.componentInstance.itemType = 'Controls';
        modalRef.componentInstance.itemName = `${publicIds.length} selected Control${publicIds.length > 1 ? 's' : ''}`;
        modalRef.componentInstance.warningMessage =
            'Controls assigned to a control measure assignment (CMA) cannot be deleted and will be skipped.';

        modalRef.result.then(
            (result) => {
                if (result !== 'confirmed') {
                    return;
                }
                this.loaderService.show();
                this.controlmeasureservice.deleteControlMeasures(publicIds)
                    .pipe(finalize(() => this.loaderService.hide()))
                    .subscribe({
                        next: (response) => {
                            this.notifyBulkDeleteResult(response);
                            this.selectedControls = [];
                            this.loadControlMeasures();
                        },
                        error: (err) => {
                            this.toast.error(err?.error?.message);
                        }
                    });
            },
            () => { /* dismissed */ }
        );
    }


    /* ------------------------------------------------------------------
    * Pagination, sorting, and search functionality
    * ------------------------------------------------------------------ */
    public onPageChange(page: number): void {
        this.selectedControls = [];
        this.page = page;
        this.loadControlMeasures();
    }

    public onPageSizeChange(limit: number): void {
        this.selectedControls = [];
        this.limit = limit;
        this.page = 1;
        this.loadControlMeasures();
    }

    public onSortChange(sort: Sort): void {
        this.selectedControls = [];
        this.sort = sort;
        this.loadControlMeasures();
    }

    public onSearchChange(search: string): void {
        this.selectedControls = [];
        this.filter = search;
        this.page = 1;
        this.loadControlMeasures();
    }

    /* ------------------------------------------------------------------
    * Helper methods
    * ------------------------------------------------------------------ */

    /*
    * Get the source name by its public_id
    */
    getSourceNames(sourceIds: number): string {
        const option = this.sourceOptions.find(opt => opt.public_id === sourceIds);
        return option?.value;
    }

    private loadImplementationStateOptions(): void {
        this.loaderService.show();
        this.extendableOptionService.getExtendableOptionsByType('IMPLEMENTATION_STATE')
            .pipe(finalize(() => this.loaderService.hide()))
            .subscribe({
                next: (res) => {
                    this.implementationStateOptions = res.results || [];
                },
                error: (err) => this.toast.error(err?.error?.message)
            });
    }

    // New method to display implementation state name instead of its ID
    getImplementationStateName(stateId: number): string {
        const option = this.implementationStateOptions.find(opt => opt.public_id === stateId);
        return option?.value;
    }


    /**
     * Surface the outcome of a bulk delete: how many controls were removed and
     * which ones were skipped because they are still assigned to a CMA.
     * @param result - Bulk delete response 
     */
    private notifyBulkDeleteResult(result: ControlMeasureBulkDeleteResult): void {
        const deletedCount = result?.successfully?.length ?? 0;
        const inUseIds = result?.in_use ?? [];

        if (deletedCount > 0) {
            this.toast.success(`${deletedCount} Control${deletedCount > 1 ? 's' : ''} deleted successfully.`);
        }

        if (inUseIds.length) {
            const names = inUseIds.map((id) => this.getControlName(id)).join(', ');
            const isPlural = inUseIds.length > 1;
            this.toast.warning(
                `${inUseIds.length} Control${isPlural ? 's' : ''} could not be deleted because ` +
                `${isPlural ? 'they are' : 'it is'} assigned to a control measure assignment (CMA): ${names}.`
            );
        }
    }


    /**
     * Resolve a control's display name by its public id, falling back to the id.
     * @param publicId - The control public id
     */
    private getControlName(publicId: number): string {
        const control = this.controlMeasures.find((item) => item.public_id === publicId);
        return control?.title ?? `#${publicId}`;
    }
}
