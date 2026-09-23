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
    Input,
    OnChanges,
    OnDestroy,
    SimpleChanges,
    inject
} from '@angular/core';

import { Observable, Subject, of } from 'rxjs';
import { catchError, finalize, switchMap, takeUntil } from 'rxjs/operators';

import { DeleteModalService } from 'src/app/core/services/delete-modal.service';
import { LoaderService } from 'src/app/core/services/loader.service';
import { PermissionService } from 'src/app/modules/auth/services/permission.service';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { Sort, SortDirection } from 'src/app/layout/table/table.types';
import {
    CONNECTION_ADD_RIGHT,
    CONNECTION_DELETE_RIGHT,
    CONNECTION_EDIT_RIGHT,
    CmdbPortConnection
} from './models/port-connection.types';
import { PortDeviceKind } from './models/port-bulk.types';
import {
    CmdbPort,
    PORT_ADD_RIGHT,
    PORT_DELETE_RIGHT,
    PORT_EDIT_RIGHT,
    PORT_VIEW_RIGHT,
    PatchPanelRow,
    PortOverviewResponse,
    PortRow
} from './models/ports-overview.types';
import { PortConnectionService } from './services/port-connection.service';
import { PortDialogService } from './services/port-dialog.service';
import { PortService } from './services/port.service';
import { distinctCableConnectionIds } from './utils/port-bulk.util';
import {
    clampPage,
    overviewPorts,
    pageRows,
    portsOfPanelRows,
    sortPatchPanelRows,
    sortPortRows,
    toCableConnection,
    toCmdbPort,
    toPatchPanelRows,
    toStandardRows
} from './utils/ports-table.util';
/* ------------------------------------------------------------------------------------------------------------------ */

const DEFAULT_PAGE_SIZE = 10;

const EMPTY_OVERVIEW: PortOverviewResponse = { device_kind: null, rows: [], total: 0 };


/** The ports section of an object view. The route sends every row at once, so paging is client-side. */
@Component({
    selector: 'cmdb-ports-overview',
    templateUrl: './ports-overview.component.html',
    styleUrls: ['./ports-overview.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    standalone: false
})
export class PortsOverviewComponent implements OnChanges, OnDestroy {

    private readonly portService = inject(PortService);
    private readonly portConnectionService = inject(PortConnectionService);
    private readonly loaderService = inject(LoaderService);
    private readonly portDialogs = inject(PortDialogService);
    private readonly deleteModal = inject(DeleteModalService);
    private readonly permission = inject(PermissionService);
    private readonly toastService = inject(ToastService);
    private readonly changesRef = inject(ChangeDetectorRef);

    @Input() public objectId: number | null = null;

    /** Ports are created from the object view; the edit form only lists them. */
    @Input() public manageable = false;

    /** Passed on as the modal's subtitle. */
    @Input() public objectLabel = '';

    /** Decides the table: one row per port, or one row per patch panel pairing. */
    public deviceKind: PortDeviceKind | null = null;

    /** The rows of the current page of a standard device. */
    public rows: PortRow[] = [];

    /** The rows of the current page of a patch panel. */
    public panelRows: PatchPanelRow[] = [];

    /** What the pagination counts. */
    public totalRows = 0;

    /** The ticked ports of the current page, which the bulk buttons act on. A pairing adds both faces. */
    public selectedRows: PortRow[] = [];

    /** Disconnecting applies to the cabled rows of the selection only. */
    public selectedConnectedRows: PortRow[] = [];

    public page = 1;
    public pageSize = DEFAULT_PAGE_SIZE;
    public sort: Sort = { name: 'port_number', order: SortDirection.ASCENDING };
    public hasError = false;
    public readonly isLoading$ = this.loaderService.isLoading$;
    public readonly portAddRight = PORT_ADD_RIGHT;
    public readonly patchPanel = PortDeviceKind.PATCH_PANEL;

    private allRows: PortRow[] = [];
    private allPanelRows: PatchPanelRow[] = [];

    /** The cables of the loaded ports, so an edit starts from the stored connection. */
    private cablesByPort = new Map<number, CmdbPortConnection>();

    /** The loaded ports by public_id, so an edit starts from the stored port and not from its row. */
    private portsById = new Map<number, CmdbPort>();

    private readonly destroy$ = new Subject<void>();
    private readonly load$ = new Subject<number>();

/* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    constructor() {
        // switchMap so a second object replaces a request still in flight instead of racing it.
        this.load$
            .pipe(
                switchMap((objectId) => this.readOverview(objectId)),
                takeUntil(this.destroy$)
            )
            .subscribe((overview) => this.applyOverview(overview));
    }

    public ngOnChanges(changes: SimpleChanges): void {
        if (changes['objectId']) {
            // A different object starts at the front; a reload after a write keeps the page.
            this.page = 1;
            this.load();
        }
    }

    public ngOnDestroy(): void {
        this.destroy$.next();
        this.destroy$.complete();
    }

/* ---------------------------------------------------- EVENTS ------------------------------------------------------ */

    public onPageChange(page: number): void {
        this.page = page;
        this.applyQuery();
    }

    public onPageSizeChange(pageSize: number): void {
        this.pageSize = pageSize;
        this.page = 1;
        this.applyQuery();
    }

    public onSortChange(sort: Sort): void {
        this.sort = sort;
        this.page = 1;
        this.applyQuery();
    }


    public onSelectedRowsChange(rows: PortRow[]): void {
        this.selectedRows = rows;
        this.selectedConnectedRows = rows.filter((row) => row.cableConnectionId != null);
    }


    public onSelectedPanelRowsChange(rows: PatchPanelRow[]): void {
        this.onSelectedRowsChange(portsOfPanelRows(rows));
    }


    /** One dialog for one port or many; the count decides, the object's kind limits the device type. */
    public onAddPorts(): void {
        if (this.objectId == null) {
            return;
        }

        this.reloadWhenStored(this.portDialogs.openAddPorts(this.objectId, this.objectLabel, this.deviceKind));
    }


    public onEditPort(row: PortRow): void {
        const port = this.portsById.get(row.publicId);

        if (!port) {
            return;
        }

        this.openForm(port);
    }


    public onDeletePort(row: PortRow): void {
        this.deleteModal.confirmDelete({
            title: 'Delete port',
            itemType: 'Port',
            itemName: row.name,
            warningMessage: 'Any connection and interface link of this port is removed with it.',
            onConfirm: () => this.remove(
                this.portService.deletePort(row.publicId),
                'Port was successfully deleted!'
            )
        });
    }


    /** Cables this port to another one. The far end is chosen inside the dialog. */
    public onConnectPort(row: PortRow): void {
        this.openConnectionForm(row, null);
    }


    public onEditConnection(row: PortRow): void {
        const cable = this.cablesByPort.get(row.publicId) ?? null;

        if (!cable) {
            return;
        }

        this.openConnectionForm(row, cable);
    }


    /** Lists the interfaces the port carries, and links or unlinks them. */
    public onManageInterfaces(row: PortRow): void {
        const port = this.portsById.get(row.publicId);

        if (!port) {
            return;
        }

        this.reloadWhenStored(this.portDialogs.openInterfaceLinks(port, this.objectLabel, {
            canEdit: this.canEdit,
            canDelete: this.canDelete
        }));
    }


    /** Writes the same status, type, speed or description onto every ticked port. */
    public onBulkEditPorts(rows: PortRow[]): void {
        if (this.objectId == null || !rows.length) {
            return;
        }

        this.reloadWhenStored(this.portDialogs.openBulkEdit(this.objectId, this.objectLabel, rows));
    }


    /** The dialog reads the delete preview itself, so the section only has to reload afterwards. */
    public onBulkDeletePorts(rows: PortRow[]): void {
        if (this.objectId == null || !rows.length) {
            return;
        }

        this.reloadWhenStored(this.portDialogs.openBulkDelete(this.objectId, this.objectLabel, rows));
    }


    /** Cuts the cables of the ticked ports. A panel's internal pairing is never part of that. */
    public onBulkDisconnectPorts(rows: PortRow[]): void {
        const objectId = this.objectId;
        const connectionIds = distinctCableConnectionIds(rows);

        if (objectId == null || !connectionIds.length) {
            return;
        }

        this.portDialogs.confirmBulkDisconnect(rows.length, connectionIds.length)
            .pipe(takeUntil(this.destroy$))
            .subscribe(() => this.remove(
                this.portConnectionService.bulkDeleteConnections(objectId, connectionIds),
                `${ connectionIds.length } connection(s) were successfully removed!`
            ));
    }


    public onDisconnectPort(row: PortRow): void {
        const cable = this.cablesByPort.get(row.publicId) ?? null;

        if (!cable) {
            return;
        }

        this.deleteModal.confirmDelete({
            title: 'Disconnect port',
            itemType: 'Connection',
            itemName: row.connectionLabel,
            warningMessage: 'The cable information is removed with the connection. Both ports stay.',
            onConfirm: () => this.remove(
                this.portConnectionService.deleteConnection(cable.public_id),
                'The ports were successfully disconnected!'
            )
        });
    }

/* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    /** Each gates one action of the table and, together, they gate its whole actions column. */
    public get canEdit(): boolean {
        return this.manageable && this.hasRight(PORT_EDIT_RIGHT);
    }


    public get canDelete(): boolean {
        return this.manageable && this.hasRight(PORT_DELETE_RIGHT);
    }


    /** Connections are guarded by their own rights: they are a fact about the cabling, not about the port. */
    public get canConnect(): boolean {
        return this.manageable && this.hasRight(CONNECTION_ADD_RIGHT);
    }


    public get canEditConnection(): boolean {
        return this.manageable && this.hasRight(CONNECTION_EDIT_RIGHT);
    }


    public get canDisconnect(): boolean {
        return this.manageable && this.hasRight(CONNECTION_DELETE_RIGHT);
    }


    /** Reading a port's interfaces is guarded by the port's own view right. */
    public get canViewInterfaces(): boolean {
        return this.hasRight(PORT_VIEW_RIGHT);
    }


    /** Without an object there is nothing to list yet, which the empty state says instead of the default. */
    public get emptyMessage(): string {
        return this.objectId == null
            ? 'Ports can be added once the object has been saved.'
            : 'No ports to display.';
    }

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    private hasRight(right: string): boolean {
        return this.permission.hasRight(right) || this.permission.hasExtendedRight(right);
    }


    /** One dialog for both port writes; it reports once the port is stored. */
    private openForm(port: CmdbPort | null): void {
        if (this.objectId == null) {
            return;
        }

        this.reloadWhenStored(this.portDialogs.openPortForm(this.objectId, this.objectLabel, port));
    }


    /** One dialog for both connection writes; the row's stored port is what it starts from. */
    private openConnectionForm(row: PortRow, connection: CmdbPortConnection | null): void {
        const port = this.portsById.get(row.publicId);

        if (!port) {
            return;
        }

        this.reloadWhenStored(this.portDialogs.openConnectionForm(port, this.objectLabel, connection));
    }


    private reloadWhenStored(stored$: Observable<void>): void {
        stored$.pipe(takeUntil(this.destroy$)).subscribe(() => this.load());
    }


    /** Both deletions report the same way; only the request and the confirmation differ. */
    private remove(request: Observable<void>, message: string): void {
        this.loaderService.show();

        request
            .pipe(
                takeUntil(this.destroy$),
                finalize(() => this.loaderService.hide())
            )
            .subscribe({
                next: () => {
                    this.toastService.success(message);
                    this.load();
                },
                error: (err) => this.toastService.error(err?.error?.message)
            });
    }


    private load(): void {
        if (this.objectId == null) {
            this.reset();
            return;
        }

        this.load$.next(this.objectId);
    }


    /** One request answers the device kind, the rows, the option labels and the cabling. */
    private readOverview(objectId: number): Observable<PortOverviewResponse> {
        this.loaderService.show();
        this.hasError = false;

        return this.portService.getPortOverview(objectId).pipe(
            catchError(() => {
                this.hasError = true;
                return of(EMPTY_OVERVIEW);
            }),
            finalize(() => {
                this.loaderService.hide();
                this.changesRef.markForCheck();
            })
        );
    }


    private applyOverview(overview: PortOverviewResponse): void {
        const objectId = this.objectId;
        const ports = overviewPorts(overview);

        this.deviceKind = overview.device_kind ?? null;
        this.allRows = overview.device_kind === PortDeviceKind.STANDARD ? toStandardRows(overview.rows) : [];
        this.allPanelRows = overview.device_kind === PortDeviceKind.PATCH_PANEL ? toPatchPanelRows(overview.rows) : [];
        this.portsById = new Map(ports.map((port) => [port.port_id, toCmdbPort(port, objectId)]));
        this.cablesByPort = new Map(ports
            .map((port) => [port.port_id, toCableConnection(port)] as const)
            .filter((entry): entry is readonly [number, CmdbPortConnection] => entry[1] !== null));
        this.applyQuery();
    }


    /** Recomputes the visible page from the full list. Nothing here talks to the server. */
    private applyQuery(): void {
        if (this.deviceKind === PortDeviceKind.PATCH_PANEL) {
            const ordered = sortPatchPanelRows(this.allPanelRows, this.sort);

            this.totalRows = ordered.length;
            this.page = clampPage(this.page, this.totalRows, this.pageSize);
            this.panelRows = pageRows(ordered, this.page, this.pageSize);
            this.rows = [];
        } else {
            const ordered = sortPortRows(this.allRows, this.sort);

            this.totalRows = ordered.length;
            this.page = clampPage(this.page, this.totalRows, this.pageSize);
            this.rows = pageRows(ordered, this.page, this.pageSize);
            this.panelRows = [];
        }

        this.clearSelection();
        this.changesRef.markForCheck();
    }


    /** New row objects never match the table's identity-based selection. */
    private clearSelection(): void {
        this.selectedRows = [];
        this.selectedConnectedRows = [];
    }


    private reset(): void {
        this.deviceKind = null;
        this.allRows = [];
        this.allPanelRows = [];
        this.portsById = new Map();
        this.cablesByPort = new Map();
        this.rows = [];
        this.panelRows = [];
        this.clearSelection();
        this.totalRows = 0;
        this.hasError = false;
        this.changesRef.markForCheck();
    }

}
