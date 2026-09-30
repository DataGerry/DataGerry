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
import { Sort, SortDirection } from 'src/app/layout/table/table.types';
import { CmdbPortConnection, ConnectionType, PortConnectionState } from '../models/port-connection.types';
import {
    CmdbPort,
    OverviewPort,
    PatchPanelOverviewRow,
    PatchPanelRow,
    PortOptionValue,
    PortOverviewResponse,
    PortRow,
    StandardOverviewRow
} from '../models/ports-overview.types';
import { summarisePortInterfaces } from './interface-row.util';
import { cableLabel } from './port-connection.util';
import { normalizeSide } from './port-side.util';
/* ------------------------------------------------------------------------------------------------------------------ */

// Port names are numbered ("Gi1/0/2", "Gi1/0/10"), so they have to collate numerically to read right.
const COLLATOR = new Intl.Collator(undefined, { numeric: true, sensitivity: 'base' });

type SortValue = string | number | boolean | null | undefined;

/** Column identifier of the standard table mapped to the row field it sorts by. */
const PORT_SORT_FIELDS: Record<string, keyof PortRow> = {
    name: 'name',
    port_number: 'portNumber',
    status: 'status',
    port_type: 'portType',
    speed: 'speed',
    connected: 'connectionLabel',
    interfaces: 'interfaceLabel',
    description: 'description'
};

/** Column identifier of the patch panel table mapped to the row field it sorts by. */
const PANEL_SORT_FIELDS: Record<string, keyof PatchPanelRow> = {
    port_number: 'portNumber',
    front: 'frontName',
    front_connection: 'frontConnection',
    paired: 'paired',
    rear: 'rearName',
    rear_connection: 'rearConnection'
};


/** One overview port as a table row. A missing option label shows a dash, never the raw id. */
export function toPortRow(port: OverviewPort): PortRow {
    const interfaces = summarisePortInterfaces(port.interface_links ?? []);
    const cabled = port.cable_connection_id != null;

    return {
        publicId: port.port_id,
        name: port.name ?? '',
        side: normalizeSide(port.side),
        portNumber: port.port_number ?? null,
        status: labelOf(port.status),
        portType: labelOf(port.port_type),
        speed: labelOf(port.speed),
        description: port.description ?? null,
        connectionState: cabled ? PortConnectionState.CABLED : PortConnectionState.FREE,
        connectionLabel: cabled ? cableLabel(port.cable) || 'Cable' : 'Free',
        cableConnectionId: port.cable_connection_id ?? null,
        farEndLabel: cabled ? farEndLabelOf(port) : null,
        interfaces,
        interfaceLabel: interfaces.label
    };
}


export function toStandardRows(rows: readonly StandardOverviewRow[]): PortRow[] {
    return rows.filter((row) => !!row?.port).map((row) => toPortRow(row.port));
}


export function toPatchPanelRows(rows: readonly PatchPanelOverviewRow[]): PatchPanelRow[] {
    return rows
        .filter((row) => !!row?.front || !!row?.rear)
        .map((row) => {
            const front = row.front ? toPortRow(row.front) : null;
            const rear = row.rear ? toPortRow(row.rear) : null;

            return {
                key: (front ?? rear).publicId,
                portNumber: front?.portNumber ?? rear?.portNumber ?? null,
                front,
                rear,
                paired: row.paired === true,
                frontName: front?.name ?? null,
                rearName: rear?.name ?? null,
                frontConnection: front?.connectionLabel ?? null,
                rearConnection: rear?.connectionLabel ?? null
            };
        });
}


/** The ports of the selected pairings, which is what every bulk action works on. */
export function portsOfPanelRows(rows: readonly PatchPanelRow[]): PortRow[] {
    return rows.flatMap((row) => [row.front, row.rear]).filter((port): port is PortRow => !!port);
}


/** Every port of an overview, whichever shape its rows have. */
export function overviewPorts(overview: PortOverviewResponse): OverviewPort[] {
    const rows: ReadonlyArray<StandardOverviewRow | PatchPanelOverviewRow> = overview?.rows ?? [];

    return rows
        .flatMap((row) => 'port' in row ? [row.port] : [row.front, row.rear])
        .filter((port): port is OverviewPort => !!port);
}


/** The stored port the edit dialogs start from, rebuilt from the option ids the overview carries. */
export function toCmdbPort(port: OverviewPort, objectId: number): CmdbPort {
    return {
        public_id: port.port_id,
        object_id: objectId,
        side: normalizeSide(port.side),
        name: port.name ?? '',
        port_number: port.port_number ?? null,
        status: port.status?.id ?? null,
        port_type: port.port_type?.id ?? null,
        speed: port.speed?.id ?? null,
        description: port.description ?? null,
        author_id: null,
        creation_time: null,
        last_edit_time: null,
        connected: port.connected === true,
        interface_links: port.interface_links ?? []
    };
}


/** The cable of a port as the connection dialog edits it; null while the port carries none. */
export function toCableConnection(port: OverviewPort): CmdbPortConnection | null {
    if (port.cable_connection_id == null) {
        return null;
    }

    const endpoints = [port.port_id, port.connected_port?.port_id]
        .filter((id): id is number => id != null)
        .sort((left, right) => left - right);

    return {
        public_id: port.cable_connection_id,
        endpoints,
        connection_type: ConnectionType.CABLE,
        cable: port.cable,
        author_id: null,
        creation_time: null,
        last_edit_time: null
    };
}


/** Orders a copy of the ports, so the loaded list keeps the order the backend sent. */
export function sortPortRows(rows: readonly PortRow[], sort: Sort): PortRow[] {
    return sortRows(rows, sort, PORT_SORT_FIELDS);
}


export function sortPatchPanelRows(rows: readonly PatchPanelRow[], sort: Sort): PatchPanelRow[] {
    return sortRows(rows, sort, PANEL_SORT_FIELDS);
}


/** The rows of one page. An out-of-range page yields nothing, which is what an empty table shows. */
export function pageRows<T>(rows: readonly T[], page: number, pageSize: number): T[] {
    if (pageSize <= 0) {
        return [...rows];
    }

    const start = Math.max(0, page - 1) * pageSize;

    return rows.slice(start, start + pageSize);
}


/** The page a result set of `total` rows has to fall back to when the current one no longer exists. */
export function clampPage(page: number, total: number, pageSize: number): number {
    if (pageSize <= 0 || total === 0) {
        return 1;
    }

    return Math.min(Math.max(1, page), Math.ceil(total / pageSize));
}

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

/** A column the table does not know keeps the backend order. */
function sortRows<T>(rows: readonly T[], sort: Sort, fields: Record<string, keyof T>): T[] {
    const field = fields[sort?.name];
    const ordered = [...rows];

    if (!field || sort.order === SortDirection.NONE) {
        return ordered;
    }

    const direction = sort.order === SortDirection.DESCENDING ? -1 : 1;

    return ordered.sort((left, right) =>
        direction * compare(left[field] as SortValue, right[field] as SortValue));
}


/** The far port and its object; a restricted object is not named at all. */
function farEndLabelOf(port: OverviewPort): string | null {
    const object = port.connected_object;

    if (!object) {
        return null;
    }

    if (object.restricted) {
        return 'Restricted object';
    }

    const objectLabel = object.label?.trim() || `Object #${ object.object_id }`;
    const portName = port.connected_port?.name?.trim();

    return portName ? `${ portName } · ${ objectLabel }` : objectLabel;
}


/** Empty values always sort last, so a table sorted by an optional column still starts with content. */
function compare(left: SortValue, right: SortValue): number {
    const leftEmpty = isEmpty(left);
    const rightEmpty = isEmpty(right);

    if (leftEmpty || rightEmpty) {
        return leftEmpty === rightEmpty ? 0 : (leftEmpty ? 1 : -1);
    }

    if (typeof left === 'number' && typeof right === 'number') {
        return left - right;
    }

    if (typeof left === 'boolean' && typeof right === 'boolean') {
        return Number(right) - Number(left);
    }

    return COLLATOR.compare(String(left), String(right));
}


function isEmpty(value: SortValue): boolean {
    return value === null || value === undefined || value === '';
}


function labelOf(option: PortOptionValue | null | undefined): string | null {
    return option?.label?.trim() || null;
}
