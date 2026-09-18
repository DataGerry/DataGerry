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

import { Column, Sort, SortDirection } from 'src/app/layout/table/table.types';
import { PortConnectionState } from '../../models/port-connection.types';
import { PortRow } from '../../models/ports-overview.types';
/* ------------------------------------------------------------------------------------------------------------------ */

/** Inputs that decide whether an optional column is part of the table. */
const OPTIONAL_COLUMN_INPUTS = [
    'showSideColumn',
    'showConnectionColumn',
    'showInterfaceColumn',
    'canEdit',
    'canDelete',
    'canConnect',
    'canEditConnection',
    'canDisconnect'
] as const;


/** Presentational port list. Owns the column definition only; every state change is handed upwards. */
@Component({
    selector: 'cmdb-ports-table',
    templateUrl: './ports-table.component.html',
    styleUrls: ['./ports-table.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    standalone: false
})
export class PortsTableComponent implements OnInit, OnChanges {

    @Input() public rows: PortRow[] = [];
    @Input() public totalRows = 0;
    @Input() public page = 1;
    @Input() public pageSize = 10;
    @Input() public sort: Sort = { name: 'port_number', order: SortDirection.ASCENDING };
    @Input() public loading = false;

    /** Patch panels are the only objects with two faces, so ordinary devices hide the side column. */
    @Input() public showSideColumn = false;

    /** Only shown once the backend reports a connection state; see `hasConnectionState`. */
    @Input() public showConnectionColumn = false;

    /** Only shown once the read route embeds the interface links; see `hasInterfaceLinks`. */
    @Input() public showInterfaceColumn = false;

    /** Each gates its own action AND, together, the whole actions column. */
    @Input() public canEdit = false;
    @Input() public canDelete = false;
    @Input() public canConnect = false;
    @Input() public canEditConnection = false;
    @Input() public canDisconnect = false;

    /** Reading the interfaces of a port is its own right, so the entry can show without write rights. */
    @Input() public canViewInterfaces = false;

    @Output() public readonly pageChange = new EventEmitter<number>();
    @Output() public readonly pageSizeChange = new EventEmitter<number>();
    @Output() public readonly sortChange = new EventEmitter<Sort>();
    @Output() public readonly editPort = new EventEmitter<PortRow>();
    @Output() public readonly deletePort = new EventEmitter<PortRow>();
    @Output() public readonly connectPort = new EventEmitter<PortRow>();
    @Output() public readonly editConnection = new EventEmitter<PortRow>();
    @Output() public readonly disconnectPort = new EventEmitter<PortRow>();
    @Output() public readonly manageInterfaces = new EventEmitter<PortRow>();

    @ViewChild('nameTemplate', { static: true }) public nameTemplate: TemplateRef<unknown>;
    @ViewChild('sideTemplate', { static: true }) public sideTemplate: TemplateRef<unknown>;
    @ViewChild('statusTemplate', { static: true }) public statusTemplate: TemplateRef<unknown>;
    @ViewChild('connectionTemplate', { static: true }) public connectionTemplate: TemplateRef<unknown>;
    @ViewChild('interfaceTemplate', { static: true }) public interfaceTemplate: TemplateRef<unknown>;
    @ViewChild('valueTemplate', { static: true }) public valueTemplate: TemplateRef<unknown>;
    @ViewChild('actionsTemplate', { static: true }) public actionsTemplate: TemplateRef<unknown>;

    public columns: Column[] = [];
    public visibleColumns: string[] = [];

    public readonly connectionState = PortConnectionState;

/* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    public ngOnInit(): void {
        this.applyColumns();
    }

    /** An optional column appears only once its input says the data or the user's rights allow it. */
    public ngOnChanges(changes: SimpleChanges): void {
        const toggled = OPTIONAL_COLUMN_INPUTS.some((input) => changes[input] && !changes[input].firstChange);

        if (toggled) {
            this.applyColumns();
        }
    }

/* ---------------------------------------------------- EVENTS ------------------------------------------------------ */

    public onPageChange(page: number): void {
        this.pageChange.emit(page);
    }

    public onPageSizeChange(pageSize: number): void {
        this.pageSizeChange.emit(pageSize);
    }

    public onSortChange(sort: Sort): void {
        this.sortChange.emit(sort);
    }

    public onEditPort(row: PortRow): void {
        this.editPort.emit(row);
    }

    public onDeletePort(row: PortRow): void {
        this.deletePort.emit(row);
    }

    public onConnectPort(row: PortRow): void {
        this.connectPort.emit(row);
    }

    public onEditConnection(row: PortRow): void {
        this.editConnection.emit(row);
    }

    public onDisconnectPort(row: PortRow): void {
        this.disconnectPort.emit(row);
    }

    public onManageInterfaces(row: PortRow): void {
        this.manageInterfaces.emit(row);
    }

/* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    /** A row without any permitted action shows a dash instead of an empty menu. */
    public hasRowActions(row: PortRow): boolean {
        return this.canEdit || this.canDelete || this.canViewInterfaces || this.hasConnectionActions(row);
    }


    /** The further interfaces of a port, one per line, as the badge's tooltip lists them. */
    public moreInterfacesTooltip(row: PortRow): string {
        return row.interfaces.additionalLabels.join('\n');
    }


    /** Connect applies to a free port; edit cable and disconnect to a cabled one. */
    public hasConnectionActions(row: PortRow): boolean {
        return row.cableConnectionId
            ? this.canEditConnection || this.canDisconnect
            : this.canConnect;
    }

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    private applyColumns(): void {
        this.columns = this.buildColumns();
        this.visibleColumns = this.columns.map((column) => column.name);
    }


    /**
     * The table renders exactly the columns it is given - `initialVisibleColumns` only feeds its reset
     * action - so a column that must not be shown is left out here instead of being hidden.
     */
    private buildColumns(): Column[] {
        const columns: Column[] = [
            {
                display: 'Port Name',
                name: 'name',
                data: 'name',
                sortable: true,
                searchable: false,
                fixed: true,
                template: this.nameTemplate,
                style: { 'min-width': '140px' }
            },
            {
                display: 'Side',
                name: 'side',
                data: 'sideLabel',
                sortable: true,
                searchable: false,
                template: this.sideTemplate,
                style: { 'min-width': '90px' }
            },
            {
                display: 'Port No.',
                name: 'port_number',
                data: 'portNumber',
                sortable: true,
                searchable: false,
                template: this.valueTemplate,
                style: { 'min-width': '90px' }
            },
            {
                display: 'Port Type',
                name: 'port_type',
                data: 'portType',
                sortable: true,
                searchable: false,
                template: this.valueTemplate,
                style: { 'min-width': '120px' }
            },
            {
                display: 'Speed',
                name: 'speed',
                data: 'speed',
                sortable: true,
                searchable: false,
                template: this.valueTemplate,
                style: { 'min-width': '120px' }
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
                display: 'Connection',
                name: 'connected',
                data: 'connectionLabel',
                sortable: true,
                searchable: false,
                template: this.connectionTemplate,
                style: { 'min-width': '180px' }
            },
            {
                display: 'Interfaces',
                name: 'interfaces',
                data: 'interfaceLabel',
                sortable: true,
                searchable: false,
                template: this.interfaceTemplate,
                style: { 'min-width': '180px' }
            },
            {
                display: 'Description',
                name: 'description',
                data: 'description',
                sortable: true,
                searchable: false,
                template: this.valueTemplate,
                style: { 'min-width': '200px' }
            },
            {
                display: 'Actions',
                name: 'actions',
                data: 'publicId',
                sortable: false,
                searchable: false,
                fixed: true,
                template: this.actionsTemplate,
                style: { 'width': '72px', 'text-align': 'center' }
            }
        ];

        return columns.filter((column) => this.isColumnShown(column.name));
    }


    private isColumnShown(name: string): boolean {
        if (name === 'side') {
            return this.showSideColumn;
        }

        if (name === 'connected') {
            return this.showConnectionColumn;
        }

        if (name === 'interfaces') {
            return this.showInterfaceColumn;
        }

        if (name === 'actions') {
            return this.canEdit || this.canDelete || this.canConnect
                || this.canEditConnection || this.canDisconnect;
        }

        return true;
    }
}
