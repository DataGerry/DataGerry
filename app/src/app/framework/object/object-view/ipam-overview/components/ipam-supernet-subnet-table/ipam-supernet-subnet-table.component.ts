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
import {
    ChangeDetectionStrategy,
    ChangeDetectorRef,
    Component,
    EventEmitter,
    Input,
    OnChanges,
    OnDestroy,
    OnInit,
    Output,
    SimpleChanges,
    TemplateRef,
    ViewChild
} from '@angular/core';
import { Subject, finalize, takeUntil } from 'rxjs';

import { LoaderService } from 'src/app/core/services/loader.service';
import { ToastService } from 'src/app/layout/toast/toast.service';

import { Column, Sort, SortDirection } from '../../../../../../layout/table/table.types';
import { IpamSubnetSummary, IpamVlanInfo } from '../../models/ipam-overview.types';
import { IpamOverviewService } from '../../services/ipam-overview.service';
/* ------------------------------------------------------------------------------------------------------------------ */

export interface SubnetDisplayRow {
    subnet: IpamSubnetSummary;
    depth: number;
    expanded: boolean;
    loadingChildren: boolean;
}

@Component({
    selector: 'cmdb-ipam-supernet-subnet-table',
    templateUrl: './ipam-supernet-subnet-table.component.html',
    styleUrls: ['./ipam-supernet-subnet-table.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    standalone: false
})
export class IpamSupernetSubnetTableComponent implements OnInit, OnChanges, OnDestroy {

    @Input() public supernetId: number | null = null;
    @Input() public rows: IpamSubnetSummary[] = [];
    @Input() public totalItems = 0;
    @Input() public page = 1;
    @Input() public pageSize = 10;
    @Input() public sort: Sort = { name: 'cidr', order: SortDirection.ASCENDING };
    @Input() public searchMode = false;
    @Input() public invalidMode = false;
    @Input() public loading = false;

    @Output() public readonly pageChange = new EventEmitter<number>();
    @Output() public readonly pageSizeChange = new EventEmitter<number>();
    @Output() public readonly sortChange = new EventEmitter<Sort>();
    @Output() public readonly unassign = new EventEmitter<number[]>();

    @ViewChild('cidrTemplate', { static: true }) public cidrTemplate: TemplateRef<unknown>;
    @ViewChild('usedTemplate', { static: true }) public usedTemplate: TemplateRef<unknown>;
    @ViewChild('freeTemplate', { static: true }) public freeTemplate: TemplateRef<unknown>;
    @ViewChild('utilizationTemplate', { static: true }) public utilizationTemplate: TemplateRef<unknown>;
    @ViewChild('vlansTemplate', { static: true }) public vlansTemplate: TemplateRef<unknown>;
    @ViewChild('actionsTemplate', { static: true }) public actionsTemplate: TemplateRef<unknown>;
    @ViewChild('bulkUnassignButton', { static: true }) public bulkUnassignButton: TemplateRef<unknown>;

    public displayRows: SubnetDisplayRow[] = [];
    public selectedRows: SubnetDisplayRow[] = [];
    public columns: Column[] = [];
    public initialVisibleColumns: string[] = [];
    public bulkButtonTemplates: TemplateRef<unknown>[] = [];

    private readonly expandedIds = new Set<number>();
    private readonly loadingIds = new Set<number>();
    private readonly childrenCache = new Map<number, IpamSubnetSummary[]>();
    private readonly destroy$ = new Subject<void>();

    constructor(
        private readonly ipamOverviewService: IpamOverviewService,
        private readonly loaderService: LoaderService,
        private readonly toastService: ToastService,
        private readonly changesRef: ChangeDetectorRef
    ) {}

/* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    public ngOnInit(): void {
        this.setupColumns();
        this.bulkButtonTemplates = [this.bulkUnassignButton];
    }

    public ngOnChanges(changes: SimpleChanges): void {
        if (changes['supernetId'] && !changes['supernetId'].firstChange) {
            this.resetExpansionState();
            this.selectedRows = [];
        }

        if (changes['rows']) {
            this.resetExpansionState();
            this.selectedRows = [];
            this.rebuildDisplayRows();
        }
    }

    public ngOnDestroy(): void {
        this.destroy$.next();
        this.destroy$.complete();
    }

/* ---------------------------------------------------- EVENTS ------------------------------------------------------ */

    public onToggleExpand(row: SubnetDisplayRow): void {
        if (this.treeDisabled || !row?.subnet?.has_children) {
            return;
        }
        const id = row.subnet.public_id;

        if (this.expandedIds.has(id)) {
            this.expandedIds.delete(id);
            this.rebuildDisplayRows();
            return;
        }

        this.expandedIds.add(id);

        if (this.childrenCache.has(id)) {
            this.rebuildDisplayRows();
            return;
        }

        this.fetchChildren(id);
    }

    public onPageChange(page: number): void {
        this.pageChange.emit(page);
    }

    public onPageSizeChange(size: number): void {
        this.pageSizeChange.emit(size);
    }

    public onSortChange(sort: Sort): void {
        this.sortChange.emit(sort);
    }

    public onSelectedChange(items: SubnetDisplayRow[]): void {
        this.selectedRows = items ?? [];
    }

    public onUnassignRow(row: SubnetDisplayRow): void {
        const id = row?.subnet?.public_id;
        if (id == null) {
            return;
        }
        this.unassign.emit([id]);
    }

    public onUnassignSelected(): void {
        const ids = this.selectedSubnetIds;
        if (!ids.length) {
            return;
        }
        this.unassign.emit(ids);
    }

/* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    public get treeDisabled(): boolean {
        return this.searchMode || this.invalidMode;
    }

    public get selectedSubnetIds(): number[] {
        const seen = new Set<number>();
        for (const row of this.selectedRows) {
            const id = row?.subnet?.public_id;
            if (id != null) {
                seen.add(id);
            }
        }
        return [...seen];
    }

    public get selectedCount(): number {
        return this.selectedSubnetIds.length;
    }

    public vlanList(vlans?: IpamVlanInfo[] | null, separator = ', '): string {
        if (!vlans?.length) {
            return '';
        }
        return vlans.map(vlan => vlan?.name).filter(Boolean).join(separator);
    }

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    private setupColumns(): void {
        this.columns = [
            {
                display: 'Subnet/CIDR',
                name: 'cidr',
                data: 'subnet.cidr',
                sortable: false,
                searchable: false,
                template: this.cidrTemplate,
                style: { 'min-width': '260px' }
            },
            {
                display: 'Used IPs',
                name: 'used_ips',
                data: 'subnet.used_ips',
                sortable: false,
                searchable: false,
                template: this.usedTemplate,
                style: { 'min-width': '150px' }
            },
            {
                display: 'Free IPs',
                name: 'free_ips',
                data: 'subnet.free_ips',
                sortable: false,
                searchable: false,
                template: this.freeTemplate,
                style: { 'min-width': '150px' }
            },
            {
                display: 'VLANs',
                name: 'vlans',
                data: 'subnet.vlans',
                sortable: false,
                searchable: false,
                template: this.vlansTemplate,
                style: { 'min-width': '160px' }
            },
            {
                display: 'Utilization',
                name: 'usage_percent',
                data: 'subnet.usage_percent',
                sortable: false,
                searchable: false,
                template: this.utilizationTemplate,
                style: { 'min-width': '120px' }
            },
            {
                display: 'Actions',
                name: 'actions',
                data: 'subnet.public_id',
                sortable: false,
                searchable: false,
                fixed: true,
                template: this.actionsTemplate,
                style: { 'width': '64px', 'text-align': 'center' }
            }
        ];

        this.initialVisibleColumns = this.columns.map(column => column.name);
    }

    private fetchChildren(subnetId: number): void {
        if (this.supernetId == null) {
            return;
        }

        this.loadingIds.add(subnetId);
        this.rebuildDisplayRows();
        this.loaderService.show();

        this.ipamOverviewService
            .getSupernetSubnetChildren(this.supernetId, subnetId)
            .pipe(
                takeUntil(this.destroy$),
                finalize(() => {
                    this.loadingIds.delete(subnetId);
                    this.loaderService.hide();
                    this.rebuildDisplayRows();
                })
            )
            .subscribe({
                next: (response) => {
                    this.childrenCache.set(subnetId, response?.rows ?? []);
                },
                error: (err) => {
                    this.expandedIds.delete(subnetId);
                    this.toastService.error(err?.error?.message);
                }
            });
    }

    private rebuildDisplayRows(): void {
        const out: SubnetDisplayRow[] = [];

        const walk = (subnet: IpamSubnetSummary, depth: number): void => {
            const expanded = this.expandedIds.has(subnet.public_id);
            const loadingChildren = this.loadingIds.has(subnet.public_id);

            out.push({ subnet, depth, expanded, loadingChildren });

            if (expanded) {
                const children = this.childrenCache.get(subnet.public_id) ?? [];
                for (const child of children) {
                    walk(child, depth + 1);
                }
            }
        };

        for (const row of this.rows ?? []) {
            walk(row, 0);
        }

        this.displayRows = out;
        this.changesRef.markForCheck();
    }

    private resetExpansionState(): void {
        this.expandedIds.clear();
        this.loadingIds.clear();
        this.childrenCache.clear();
    }
}
