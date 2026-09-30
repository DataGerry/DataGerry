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
import { PatchPanelRow, PortRow } from '../../models/ports-overview.types';
/* ------------------------------------------------------------------------------------------------------------------ */

/** Inputs that decide whether the actions column is part of the table. */
const ACTION_INPUTS = ['canEdit', 'canDelete', 'canConnect', 'canEditConnection', 'canDisconnect'] as const;


/** Presentational list of a patch panel, one row per front/rear pairing. Every state change is handed upwards. */
@Component({
    selector: 'cmdb-patch-panel-table',
    templateUrl: './patch-panel-table.component.html',
    styleUrls: ['../ports-table/ports-table.component.scss', './patch-panel-table.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    standalone: false
})
export class PatchPanelTableComponent implements OnInit, OnChanges {

    @Input() public rows: PatchPanelRow[] = [];
    @Input() public totalRows = 0;
    @Input() public page = 1;
    @Input() public pageSize = 10;
    @Input() public sort: Sort = { name: 'port_number', order: SortDirection.ASCENDING };
    @Input() public loading = false;
    @Input() public emptyMessage = 'No ports to display.';

    /** Each gates its own action AND, together, the whole actions column. */
    @Input() public canEdit = false;
    @Input() public canDelete = false;
    @Input() public canConnect = false;
    @Input() public canEditConnection = false;
    @Input() public canDisconnect = false;
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

    /** Not re-emitted when the rows change: whoever replaces the rows drops its own selection. */
    @Output() public readonly selectedRowsChange = new EventEmitter<PatchPanelRow[]>();

    @ViewChild('frontTemplate', { static: true }) public frontTemplate: TemplateRef<unknown>;
    @ViewChild('frontConnectionTemplate', { static: true }) public frontConnectionTemplate: TemplateRef<unknown>;
    @ViewChild('pairedTemplate', { static: true }) public pairedTemplate: TemplateRef<unknown>;
    @ViewChild('rearTemplate', { static: true }) public rearTemplate: TemplateRef<unknown>;
    @ViewChild('rearConnectionTemplate', { static: true }) public rearConnectionTemplate: TemplateRef<unknown>;
    @ViewChild('valueTemplate', { static: true }) public valueTemplate: TemplateRef<unknown>;
    @ViewChild('actionsTemplate', { static: true }) public actionsTemplate: TemplateRef<unknown>;

    public columns: Column[] = [];
    public visibleColumns: string[] = [];
    public selectedRows: PatchPanelRow[] = [];

    public readonly connectionState = PortConnectionState;

    /** The columns the user unticked. Kept for this view only - nothing is persisted. */
    private readonly hiddenColumnNames = new Set<string>();

/* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    public ngOnInit(): void {
        this.applyColumns();
    }

    public ngOnChanges(changes: SimpleChanges): void {
        // A reload builds new row objects, and the table matches a selection by identity.
        if (changes['rows']) {
            this.selectedRows = [];
        }

        if (ACTION_INPUTS.some((input) => changes[input] && !changes[input].firstChange)) {
            this.applyColumns();
        }
    }

/* ---------------------------------------------------- EVENTS ------------------------------------------------------ */

    /** The table drops its own selection on a page change without reporting it, so this mirrors it. */
    public onPageChange(page: number): void {
        this.selectedRows = [];
        this.pageChange.emit(page);
    }

    public onPageSizeChange(pageSize: number): void {
        this.selectedRows = [];
        this.pageSizeChange.emit(pageSize);
    }

    public onSortChange(sort: Sort): void {
        this.selectedRows = [];
        this.sortChange.emit(sort);
    }

    /** The table mutates `hidden` itself; this only remembers it so a rebuild keeps the choice. */
    public onColumnVisibilityChange(column?: Column): void {
        if (!column) {
            this.hiddenColumnNames.clear();
            return;
        }

        if (column.hidden) {
            this.hiddenColumnNames.add(column.name);
        } else {
            this.hiddenColumnNames.delete(column.name);
        }
    }

    public onSelectedChange(rows: PatchPanelRow[]): void {
        this.selectedRows = rows ?? [];
        this.selectedRowsChange.emit([...this.selectedRows]);
    }

    public onEditPort(port: PortRow): void {
        this.editPort.emit(port);
    }

    public onDeletePort(port: PortRow): void {
        this.deletePort.emit(port);
    }

    public onConnectPort(port: PortRow): void {
        this.connectPort.emit(port);
    }

    public onEditConnection(port: PortRow): void {
        this.editConnection.emit(port);
    }

    public onDisconnectPort(port: PortRow): void {
        this.disconnectPort.emit(port);
    }

    public onManageInterfaces(port: PortRow): void {
        this.manageInterfaces.emit(port);
    }

/* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    public get selectEnabled(): boolean {
        return this.canEdit || this.canDelete || this.canDisconnect;
    }


    /** A pairing whose ports offer no permitted action shows a dash instead of an empty menu. */
    public hasRowActions(row: PatchPanelRow): boolean {
        return this.hasPortActions(row.front) || this.hasPortActions(row.rear);
    }


    public hasPortActions(port: PortRow | null): boolean {
        return !!port && (this.canEdit || this.canDelete || this.canViewInterfaces || this.hasConnectionActions(port));
    }


    /** Connect applies to a free port; edit cable and disconnect to a cabled one. */
    public hasConnectionActions(port: PortRow): boolean {
        return port.cableConnectionId
            ? this.canEditConnection || this.canDisconnect
            : this.canConnect;
    }


    public pairingLabel(row: PatchPanelRow): string {
        return row.paired ? 'Paired' : 'Not paired';
    }

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    private applyColumns(): void {
        this.columns = this.buildColumns();
        this.visibleColumns = this.columns.map((column) => column.name);

        for (const column of this.columns) {
            column.hidden = this.hiddenColumnNames.has(column.name);
        }
    }


    private buildColumns(): Column[] {
        const columns: Column[] = [
            {
                display: 'No.',
                name: 'port_number',
                data: 'portNumber',
                sortable: true,
                searchable: false,
                template: this.valueTemplate,
                style: { 'width': '70px' }
            },
            {
                display: 'Front Port',
                name: 'front',
                data: 'frontName',
                sortable: true,
                searchable: false,
                fixed: true,
                template: this.frontTemplate,
                style: { 'min-width': '140px' }
            },
            {
                display: 'Front Connection',
                name: 'front_connection',
                data: 'frontConnection',
                sortable: true,
                searchable: false,
                template: this.frontConnectionTemplate,
                style: { 'min-width': '180px' }
            },
            {
                display: 'Pairing',
                name: 'paired',
                data: 'paired',
                sortable: true,
                searchable: false,
                template: this.pairedTemplate,
                style: { 'width': '110px', 'text-align': 'center' }
            },
            {
                display: 'Rear Port',
                name: 'rear',
                data: 'rearName',
                sortable: true,
                searchable: false,
                template: this.rearTemplate,
                style: { 'min-width': '140px' }
            },
            {
                display: 'Rear Connection',
                name: 'rear_connection',
                data: 'rearConnection',
                sortable: true,
                searchable: false,
                template: this.rearConnectionTemplate,
                style: { 'min-width': '180px' }
            },
            {
                display: 'Actions',
                name: 'actions',
                data: 'key',
                sortable: false,
                searchable: false,
                fixed: true,
                template: this.actionsTemplate,
                style: { 'width': '72px', 'text-align': 'center' }
            }
        ];

        const hasActions = this.canEdit || this.canDelete || this.canConnect
            || this.canEditConnection || this.canDisconnect;

        return hasActions ? columns : columns.filter((column) => column.name !== 'actions');
    }
}
