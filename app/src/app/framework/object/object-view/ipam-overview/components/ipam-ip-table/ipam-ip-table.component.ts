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
    Component,
    EventEmitter,
    Input,
    OnChanges,
    OnInit,
    Output,
    SimpleChanges,
    TemplateRef,
    ViewChild
} from '@angular/core';

import { Column, Sort, SortDirection } from '../../../../../../layout/table/table.types';
import { IpamIpEntry } from '../../models/ipam-overview.types';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'cmdb-ipam-ip-table',
    templateUrl: './ipam-ip-table.component.html',
    styleUrls: ['./ipam-ip-table.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    standalone: false
})
export class IpamIpTableComponent implements OnInit, OnChanges {

    @Input() public items: IpamIpEntry[] = [];
    @Input() public totalItems = 0;
    @Input() public page = 1;
    @Input() public pageSize = 10;
    @Input() public sort: Sort = { name: 'ip', order: SortDirection.ASCENDING };
    @Input() public loading = false;

    @Output() public readonly pageChange = new EventEmitter<number>();
    @Output() public readonly pageSizeChange = new EventEmitter<number>();
    @Output() public readonly sortChange = new EventEmitter<Sort>();
    @Output() public readonly unassign = new EventEmitter<string[]>();

    @ViewChild('statusTemplate', { static: true }) public statusTemplate: TemplateRef<unknown>;
    @ViewChild('typeTemplate', { static: true }) public typeTemplate: TemplateRef<unknown>;
    @ViewChild('assignedToTemplate', { static: true }) public assignedToTemplate: TemplateRef<unknown>;
    @ViewChild('valueTemplate', { static: true }) public valueTemplate: TemplateRef<unknown>;
    @ViewChild('actionsTemplate', { static: true }) public actionsTemplate: TemplateRef<unknown>;
    @ViewChild('bulkUnassignButton', { static: true }) public bulkUnassignButton: TemplateRef<unknown>;

    public columns: Column[] = [];
    public initialVisibleColumns: string[] = [];
    public selectedRows: IpamIpEntry[] = [];
    public bulkButtonTemplates: TemplateRef<unknown>[] = [];

/* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    public ngOnInit(): void {
        this.setupColumns();
        this.bulkButtonTemplates = [this.bulkUnassignButton];
    }

    public ngOnChanges(changes: SimpleChanges): void {
        if (changes['items']) {
            this.selectedRows = [];
        }
    }

/* ---------------------------------------------------- EVENTS ------------------------------------------------------ */

    public onPageChange(page: number): void {
        this.pageChange.emit(page);
    }

    public onPageSizeChange(size: number): void {
        this.pageSizeChange.emit(size);
    }

    public onSortChange(sort: Sort): void {
        this.sortChange.emit(sort);
    }

    public onSelectedChange(items: IpamIpEntry[]): void {
        this.selectedRows = items ?? [];
    }

    public onUnassignRow(item: IpamIpEntry): void {
        if (!this.canUnassign(item)) {
            return;
        }
        this.unassign.emit([item.ip]);
    }

    public onUnassignSelected(): void {
        const ips = this.selectedUnassignableIps;
        if (!ips.length) {
            return;
        }
        this.unassign.emit(ips);
    }

/* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    public get selectedUnassignableIps(): string[] {
        const seen = new Set<string>();
        for (const item of this.selectedRows) {
            if (this.canUnassign(item)) {
                seen.add(item.ip);
            }
        }
        return [...seen];
    }

    public get selectedCount(): number {
        return this.selectedUnassignableIps.length;
    }

    public canUnassign(item: IpamIpEntry): boolean {
        return !!item?.assigned_to;
    }

    public trackByIp(_index: number, item: IpamIpEntry): string {
        return item?.ip;
    }

    public statusLabel(status?: string): string {
        if (!status) {
            return 'Used';
        }
        return status.charAt(0).toUpperCase() + status.slice(1);
    }

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    private setupColumns(): void {
        this.columns = [
            {
                display: 'IP Address',
                name: 'ip',
                data: 'ip',
                sortable: false,
                searchable: false,
                style: { 'min-width': '120px' }
            },
            {
                display: 'Type',
                name: 'type_info',
                data: 'type_info',
                sortable: false,
                searchable: false,
                template: this.typeTemplate,
                style: { 'min-width': '100px', 'text-align': 'center' }
            },
            {
                display: 'Status',
                name: 'status',
                data: 'status',
                sortable: false,
                searchable: false,
                template: this.statusTemplate,
                style: { 'min-width': '120px' }
            },
            {
                display: 'Assigned To',
                name: 'assigned_to',
                data: 'assigned_to',
                sortable: false,
                searchable: false,
                template: this.assignedToTemplate,
                style: { 'min-width': '180px' }
            },
            {
                display: 'MAC Address',
                name: 'mac_address',
                data: 'mac_address',
                sortable: false,
                searchable: false,
                template: this.valueTemplate,
                style: { 'min-width': '180px' }
            },
            {
                display: 'Actions',
                name: 'actions',
                data: 'ip',
                sortable: false,
                searchable: false,
                fixed: true,
                template: this.actionsTemplate,
                style: { 'width': '64px', 'text-align': 'center' }
            }
        ];

        this.initialVisibleColumns = this.columns.map(column => column.name);
    }
}
