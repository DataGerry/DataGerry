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
    ChangeDetectionStrategy,
    Component,
    computed,
    DestroyRef,
    inject,
    OnInit,
    signal,
    TemplateRef,
    viewChild
} from '@angular/core';
import { AsyncPipe } from '@angular/common';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { NgbModal, NgbModalRef } from '@ng-bootstrap/ng-bootstrap';
import { forkJoin, of } from 'rxjs';
import { catchError, finalize, map } from 'rxjs/operators';

import { CoreModule } from 'src/app/core/core.module';
import { TableModule } from 'src/app/layout/table/table.module';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { LoaderService } from 'src/app/core/services/loader.service';
import { FilterBuilderService } from 'src/app/core/services/filter-builder.service';
import { CoreDeleteConfirmationModalComponent } from 'src/app/core/components/dialog/delete-dialog/core-delete-confirmation-modal.component';
import { PermissionService } from 'src/app/modules/auth/services/permission.service';
import { CollectionParameters } from 'src/app/services/models/api-parameter';
import { Column, Sort, SortDirection } from 'src/app/layout/table/table.types';
import { ExtendableOption } from 'src/app/framework/models/object-group.model';
import { ControlMeasure, ControlMeasureBulkDeleteResult } from '../../models/control-measure.model';
import { ControlMeasureService } from '../../services/control-measure.service';
import { ExtendableOptionService } from '../../services/extendable-option.service';
import { OscalCatalogService } from '../../services/oscal-catalog.service';

/** Controls without a catalog_id (created by hand or via CSV). */
export const CUSTOM_CONTROLS_ID = 'custom';

interface ControlCatalogEntry {
    id: string;
    title: string;
    description: string;
    count: number | null;
}

interface CatalogMatchStage {
    $match: { catalog_id: string | null };
}

interface ControlRowTemplateContext {
    data: unknown;
    item: ControlMeasure;
}

@Component({
    selector: 'app-control-measures-list',
    templateUrl: './control-measures-list.component.html',
    styleUrls: ['./control-measures-list.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    imports: [AsyncPipe, RouterLink, CoreModule, TableModule]
})
export class ControlmeasuresListComponent implements OnInit {
    private readonly actionTemplate = viewChild.required<TemplateRef<ControlRowTemplateContext>>('actionTemplate');
    private readonly implementationStateTemplate =
        viewChild.required<TemplateRef<ControlRowTemplateContext>>('implementationStateTemplate');

    private readonly router = inject(Router);
    private readonly route = inject(ActivatedRoute);
    private readonly toast = inject(ToastService);
    private readonly loaderService = inject(LoaderService);
    private readonly modalService = inject(NgbModal);
    private readonly filterBuilderService = inject(FilterBuilderService);
    private readonly permissionService = inject(PermissionService);
    private readonly controlMeasureService = inject(ControlMeasureService);
    private readonly extendableOptionService = inject(ExtendableOptionService);
    private readonly catalogService = inject(OscalCatalogService);
    private readonly destroyRef = inject(DestroyRef);

    public readonly isLoading$ = this.loaderService.isLoading$;

    public readonly controlMeasures = signal<ControlMeasure[]>([]);
    public readonly totalControlMeasures = signal(0);
    public readonly selectedControls = signal<ControlMeasure[]>([]);

    public readonly page = signal(1);
    public readonly limit = signal(10);
    public readonly loading = signal(false);
    public readonly filter = signal('');
    public readonly sort = signal<Sort>({ name: 'public_id', order: SortDirection.DESCENDING });
    public columns: Column[] = [];
    public initialVisibleColumns: string[] = [];

    public readonly implementationStateOptions = signal<ExtendableOption[]>([]);

    // Catalog picker; null until a catalog is chosen
    public readonly catalogEntries = signal<ControlCatalogEntry[]>([]);
    public readonly selectedCatalogId = signal<string | null>(null);

    public readonly selectedCatalogTitle = computed(() => {
        const catalogId = this.selectedCatalogId();
        if (catalogId === CUSTOM_CONTROLS_ID) {
            return 'Custom controls';
        }
        return this.catalogEntries().find(entry => entry.id === catalogId)?.title ?? catalogId ?? '';
    });

    public readonly canView = this.hasRight('base.isms.controlMeasure.view');
    public readonly canAdd = this.hasRight('base.isms.controlMeasure.add');
    public readonly canEdit = this.hasRight('base.isms.controlMeasure.edit');
    public readonly canDelete = this.hasRight('base.isms.controlMeasure.delete');

    /* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    ngOnInit(): void {
        this.setupColumns();
        this.loadImplementationStateOptions();

        this.route.queryParamMap
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe(params => {
                const catalogId = params.get('catalog');
                this.selectedCatalogId.set(catalogId);
                this.controlMeasures.set([]);
                this.selectedControls.set([]);
                this.page.set(1);
                this.filter.set('');

                if (catalogId) {
                    this.loadControlMeasures();
                }

                // A directly linked catalog still needs the entries for its title
                if (!catalogId || !this.catalogEntries().length) {
                    this.loadCatalogEntries();
                }
            });
    }

    /* ---------------------------------------------------- EVENTS ------------------------------------------------------ */

    public selectCatalog(entry: ControlCatalogEntry): void {
        this.router.navigate([], { relativeTo: this.route, queryParams: { catalog: entry.id } });
    }

    public onCatalogCardKeydown(event: Event, entry: ControlCatalogEntry): void {
        event.preventDefault();
        this.selectCatalog(entry);
    }

    public changeCatalog(): void {
        this.router.navigate([], { relativeTo: this.route, queryParams: {} });
    }

    public onAddNew(): void {
        this.router.navigate(['/isms/control-measures/add']);
    }

    public onView(item: ControlMeasure): void {
        this.router.navigate(['/isms/control-measures/view'], { state: { controlMeasure: item, mode: 'view' } });
    }

    public onEdit(item: ControlMeasure): void {
        this.router.navigate(['/isms/control-measures/edit'], { state: { controlMeasure: item } });
    }

    public onDelete(item: ControlMeasure): void {
        if (!item.public_id) {
            return;
        }

        const modalRef = this.openDeleteModal();
        modalRef.componentInstance.title = 'Delete Control';
        modalRef.componentInstance.item = item;
        modalRef.componentInstance.itemType = 'Control';
        modalRef.componentInstance.itemName = item.title;

        modalRef.result.then(
            result => {
                if (result !== 'confirmed') {
                    return;
                }
                this.loaderService.show();
                this.controlMeasureService.deleteControlMeasure(item.public_id)
                    .pipe(
                        finalize(() => this.loaderService.hide()),
                        takeUntilDestroyed(this.destroyRef)
                    )
                    .subscribe({
                        next: () => {
                            this.toast.success('Control deleted successfully.');
                            this.loadControlMeasures();
                        },
                        error: () => this.toast.error('The control could not be deleted.')
                    });
            },
            () => { /* dismissed */ }
        );
    }

    /** Controls assigned to a control measure assignment (CMA) are reported back as skipped. */
    public onDeleteSelected(): void {
        const selected = this.selectedControls();
        const publicIds = selected
            .map(control => control.public_id)
            .filter((id): id is number => id != null);

        if (!publicIds.length) {
            return;
        }

        const modalRef = this.openDeleteModal();
        modalRef.componentInstance.title = 'Delete Controls';
        modalRef.componentInstance.item = selected;
        modalRef.componentInstance.itemType = 'Controls';
        modalRef.componentInstance.itemName = `${publicIds.length} selected Control${publicIds.length > 1 ? 's' : ''}`;
        modalRef.componentInstance.warningMessage =
            'Controls assigned to a control measure assignment (CMA) cannot be deleted and will be skipped.';

        modalRef.result.then(
            result => {
                if (result !== 'confirmed') {
                    return;
                }
                this.loaderService.show();
                this.controlMeasureService.deleteControlMeasures(publicIds)
                    .pipe(
                        finalize(() => this.loaderService.hide()),
                        takeUntilDestroyed(this.destroyRef)
                    )
                    .subscribe({
                        next: response => {
                            this.notifyBulkDeleteResult(response);
                            this.selectedControls.set([]);
                            this.loadControlMeasures();
                        },
                        error: () => this.toast.error('The selected controls could not be deleted.')
                    });
            },
            () => { /* dismissed */ }
        );
    }

    public onSelectedChange(selected: ControlMeasure[]): void {
        this.selectedControls.set(selected ?? []);
    }

    public onPageChange(page: number): void {
        this.selectedControls.set([]);
        this.page.set(page);
        this.loadControlMeasures();
    }

    public onPageSizeChange(limit: number): void {
        this.selectedControls.set([]);
        this.limit.set(limit);
        this.page.set(1);
        this.loadControlMeasures();
    }

    public onSortChange(sort: Sort): void {
        this.selectedControls.set([]);
        this.sort.set(sort);
        this.loadControlMeasures();
    }

    public onSearchChange(search: string): void {
        this.selectedControls.set([]);
        this.filter.set(search);
        this.page.set(1);
        this.loadControlMeasures();
    }

    /* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    public getImplementationStateName(stateId: number): string | undefined {
        return this.implementationStateOptions().find(option => option.public_id === stateId)?.value;
    }

    /* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

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
            {
                display: 'Identifier',
                name: 'identifier',
                data: 'identifier',
                searchable: true,
                sortable: false,
                style: { width: '150px', 'text-align': 'center' }
            },
            {
                display: 'Chapter',
                name: 'chapter',
                data: 'chapter',
                searchable: true,
                sortable: true,
                style: { width: '220px' }
            },
            {
                display: 'Implementation State',
                name: 'implementation_state',
                data: 'implementation_state',
                searchable: true,
                sortable: false,
                template: this.implementationStateTemplate(),
                style: { width: '150px', 'text-align': 'center' }
            },
            {
                display: 'Actions',
                name: 'actions',
                data: 'public_id',
                searchable: false,
                sortable: false,
                fixed: true,
                template: this.actionTemplate(),
                style: { width: '80px', 'text-align': 'center' }
            }
        ];
        this.initialVisibleColumns = this.columns.map(column => column.name);
    }

    private loadControlMeasures(): void {
        this.loading.set(true);
        this.loaderService.show();

        const filterQuery = this.filterBuilderService.buildFilter(
            this.filter(),
            [
                { name: 'title' },
                { name: 'identifier' },
                { name: 'chapter' },
                { name: 'control_measure_type' }
            ]
        );

        const params: CollectionParameters = {
            filter: [this.catalogMatch(this.selectedCatalogId()), ...filterQuery],
            limit: this.limit(),
            page: this.page(),
            sort: this.sort().name,
            order: this.sort().order
        };

        this.controlMeasureService.getControlMeasures(params)
            .pipe(
                finalize(() => {
                    this.loading.set(false);
                    this.loaderService.hide();
                }),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe({
                next: resp => {
                    this.controlMeasures.set(resp.results);
                    this.totalControlMeasures.set(resp.total);
                },
                error: () => this.toast.error('The controls could not be loaded.')
            });
    }

    /** catalog_status has no entry for custom controls, so those are counted separately. */
    private loadCatalogEntries(): void {
        this.loaderService.show();

        forkJoin({
            catalogs: this.catalogService.getManifest().pipe(
                map(manifest => manifest.catalogs ?? []),
                catchError(() => of([]))
            ),
            counts: this.controlMeasureService.getCatalogStatus().pipe(catchError(() => of(null))),
            customCount: this.controlMeasureService.getControlMeasures({
                filter: [this.catalogMatch(CUSTOM_CONTROLS_ID)],
                limit: 1,
                page: 1,
                sort: 'public_id',
                order: SortDirection.ASCENDING
            }).pipe(
                map(resp => resp.total),
                catchError(() => of(null))
            )
        })
            .pipe(
                finalize(() => this.loaderService.hide()),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe(({ catalogs, counts, customCount }) => {
                this.catalogEntries.set([
                    ...catalogs.map(catalog => ({
                        id: catalog.id,
                        title: catalog.title,
                        description: `${catalog.publisher} · ${catalog.version}`,
                        count: counts ? counts[catalog.id] ?? 0 : null
                    })),
                    {
                        id: CUSTOM_CONTROLS_ID,
                        title: 'Custom controls',
                        description: 'Controls created by hand or via CSV import',
                        count: customCount
                    }
                ]);
            });
    }

    private loadImplementationStateOptions(): void {
        this.loaderService.show();
        this.extendableOptionService.getExtendableOptionsByType('IMPLEMENTATION_STATE')
            .pipe(
                finalize(() => this.loaderService.hide()),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe({
                next: res => this.implementationStateOptions.set(res.results ?? []),
                error: () => this.toast.error('The implementation states could not be loaded.')
            });
    }

    private catalogMatch(catalogId: string | null): CatalogMatchStage {
        return { $match: { catalog_id: !catalogId || catalogId === CUSTOM_CONTROLS_ID ? null : catalogId } };
    }

    private openDeleteModal(): NgbModalRef {
        return this.modalService.open(CoreDeleteConfirmationModalComponent, {
            size: 'lg',
            windowClass: 'dg-modal-window',
            backdropClass: 'dg-modal-window-backdrop'
        });
    }

    private notifyBulkDeleteResult(result: ControlMeasureBulkDeleteResult): void {
        const deletedCount = result?.successfully?.length ?? 0;
        const inUseIds = result?.in_use ?? [];

        if (deletedCount > 0) {
            this.toast.success(`${deletedCount} Control${deletedCount > 1 ? 's' : ''} deleted successfully.`);
        }

        if (inUseIds.length) {
            const names = inUseIds.map(id => this.getControlName(id)).join(', ');
            const isPlural = inUseIds.length > 1;
            this.toast.warning(
                `${inUseIds.length} Control${isPlural ? 's' : ''} could not be deleted because ` +
                `${isPlural ? 'they are' : 'it is'} assigned to a control measure assignment (CMA): ${names}.`
            );
        }
    }

    /** Falls back to the id when the control is not on the current page. */
    private getControlName(publicId: number): string {
        const control = this.controlMeasures().find(item => item.public_id === publicId);
        return control?.title ?? `#${publicId}`;
    }

    private hasRight(right: string): boolean {
        return this.permissionService.hasRight(right) || this.permissionService.hasExtendedRight(right);
    }
}
