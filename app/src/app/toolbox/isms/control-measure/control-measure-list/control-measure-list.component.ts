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

* You should have received a copy of the GNU Affero General Public License
* along with this program. If not, see <https://www.gnu.org/licenses/>.
*/
import {
    Component,
    OnInit,
    TemplateRef,
    ViewChild
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
import { ControlMeasure } from '../../models/control-measure.model';
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

    constructor(
        private router: Router,
        private toast: ToastService,
        private loaderService: LoaderService,
        private modalService: NgbModal,
        private filterBuilderService: FilterBuilderService,
        private controlmeasureservice: ControlMeasureService,
        private extendableOptionService: ExtendableOptionService

    ) { }

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
        const modalRef = this.modalService.open(CoreDeleteConfirmationModalComponent, { size: 'lg' });
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


    /* ------------------------------------------------------------------
    * Pagination, sorting, and search functionality
    * ------------------------------------------------------------------ */
    public onPageChange(page: number): void {
        this.page = page;
        this.loadControlMeasures();
    }

    public onPageSizeChange(limit: number): void {
        this.limit = limit;
        this.page = 1;
        this.loadControlMeasures();
    }

    public onSortChange(sort: Sort): void {
        this.sort = sort;
        this.loadControlMeasures();
    }

    public onSearchChange(search: string): void {
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
}
