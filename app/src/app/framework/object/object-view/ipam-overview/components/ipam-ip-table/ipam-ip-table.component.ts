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
    OnInit,
    Output,
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
export class IpamIpTableComponent implements OnInit {

    @Input() public items: IpamIpEntry[] = [];
    @Input() public totalItems = 0;
    @Input() public page = 1;
    @Input() public pageSize = 10;
    @Input() public sort: Sort = { name: 'ip', order: SortDirection.ASCENDING };
    @Input() public loading = false;

    @Output() public readonly pageChange = new EventEmitter<number>();
    @Output() public readonly pageSizeChange = new EventEmitter<number>();
    @Output() public readonly sortChange = new EventEmitter<Sort>();
    @Output() public readonly selectionChange = new EventEmitter<IpamIpEntry[]>();

    @ViewChild('statusTemplate', { static: true }) public statusTemplate: TemplateRef<unknown>;
    @ViewChild('typeTemplate', { static: true }) public typeTemplate: TemplateRef<unknown>;
    @ViewChild('valueTemplate', { static: true }) public valueTemplate: TemplateRef<unknown>;

    public columns: Column[] = [];
    public initialVisibleColumns: string[] = [];

/* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    public ngOnInit(): void {
        this.setupColumns();
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

    public onSelectedChange(selected: IpamIpEntry[]): void {
        this.selectionChange.emit(selected);
    }

/* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    public trackByIp(_index: number, item: IpamIpEntry): string {
        return item?.ip;
    }

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    private setupColumns(): void {
        this.columns = [
            {
                display: 'IP Address',
                name: 'ip',
                data: 'ip',
                sortable: true,
                searchable: false,
                style: { 'min-width': '160px' }
            },
            {
                display: 'Type',
                name: 'type_info',
                data: 'type_info',
                sortable: true,
                searchable: false,
                template: this.typeTemplate,
                style: { 'min-width': '110px' }
            },
            {
                display: 'Status',
                name: 'status',
                data: 'status',
                sortable: true,
                searchable: false,
                template: this.statusTemplate,
                style: { 'min-width': '120px' }
            },
            {
                display: 'Assigned To',
                name: 'assigned_to',
                data: 'assigned_to',
                sortable: true,
                searchable: false,
                template: this.valueTemplate,
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
                display: 'Last Seen',
                name: 'last_seen',
                data: 'last_seen',
                sortable: true,
                searchable: false,
                template: this.valueTemplate,
                style: { 'min-width': '160px' }
            }
        ];

        this.initialVisibleColumns = this.columns.map(column => column.name);
    }
}
