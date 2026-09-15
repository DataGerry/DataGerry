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
import { FieldOption } from 'src/app/framework/models/cmdb-section-template';
import { Sort, SortDirection } from 'src/app/layout/table/table.types';
import { PortConnectionInfo, PortConnectionState } from '../models/port-connection.types';
import { CmdbPort, PortRow, PortSide } from '../models/ports-overview.types';
import { cableSummary, peerPortIdOf } from './port-connection.util';
import { normalizeSide, portSideLabel } from './port-side.util';
/* ------------------------------------------------------------------------------------------------------------------ */

// Port names are numbered ("Gi1/0/2", "Gi1/0/10"), so they have to collate numerically to read right.
const COLLATOR = new Intl.Collator(undefined, { numeric: true, sensitivity: 'base' });

/** Column identifier of the table mapped to the row field it sorts by. */
const SORT_FIELDS: Record<string, keyof PortRow> = {
    name: 'name',
    side: 'sideLabel',
    port_number: 'portNumber',
    status: 'status',
    port_type: 'portType',
    speed: 'speed',
    connected: 'connectionLabel',
    description: 'description'
};


/**
 * Builds the table rows. An option id with no label shows a dash, never the raw number.
 *
 * `connectionsByPort` is what the connection cell reads. Without it every port reports as free -
 * a section that may not read the connections still lists the ports.
 */
export function toPortRows(
    ports: readonly CmdbPort[],
    labels: Map<string, string>,
    connectionsByPort: Map<number, PortConnectionInfo> = new Map()
): PortRow[] {
    const namesByPortId = new Map(ports.map((port) => [port.public_id, port.name ?? '']));

    return ports.map((port) => {
        const side = normalizeSide(port.side);
        const connection = connectionsByPort.get(port.public_id) ?? null;
        const pairedPortName = pairedPortNameOf(connection, port.public_id, namesByPortId);

        return {
            publicId: port.public_id,
            name: port.name ?? '',
            side,
            sideLabel: portSideLabel(side),
            portNumber: port.port_number ?? null,
            status: labelOf(port.status, labels),
            portType: labelOf(port.port_type, labels),
            speed: labelOf(port.speed, labels),
            description: port.description ?? null,
            connected: port.connected === true,
            connectionState: connection?.state ?? PortConnectionState.FREE,
            connectionLabel: connectionLabelOf(connection, pairedPortName),
            cableConnectionId: connection?.cable?.public_id ?? null,
            pairedPortName
        };
    });
}


/** Flattens the catalog's per-type option lists into one `public_id -> label` lookup. */
export function toOptionLabels(optionsByType: Map<string, FieldOption[]>): Map<string, string> {
    const labels = new Map<string, string>();

    for (const options of optionsByType.values()) {
        for (const option of options) {
            labels.set(String(option.name), option.label);
        }
    }

    return labels;
}


/** Whether the backend sends `connected` at all; without it the column would claim "Free" for every port. */
export function hasConnectionState(ports: readonly CmdbPort[]): boolean {
    return ports.some((port) => 'connected' in port);
}


/** True as soon as one port sits on a panel face, which is what makes the side column worth showing. */
export function hasPanelSides(rows: readonly PortRow[]): boolean {
    return rows.some((row) => row.side === PortSide.FRONT || row.side === PortSide.REAR);
}


/** Orders a copy of the full list, so the loaded ports keep the order the backend sent. */
export function sortPortRows(rows: readonly PortRow[], sort: Sort): PortRow[] {
    const field = SORT_FIELDS[sort?.name];
    const ordered = [...rows];

    if (!field || sort.order === SortDirection.NONE) {
        return ordered;
    }

    const direction = sort.order === SortDirection.DESCENDING ? -1 : 1;

    return ordered.sort((left, right) => direction * compare(left[field], right[field]));
}


/** The rows of one page. An out-of-range page yields nothing, which is what an empty table shows. */
export function pagePortRows(rows: readonly PortRow[], page: number, pageSize: number): PortRow[] {
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

/** A cabled port reads as its cable, a paired one as its counterpart, and a free one as free. */
function connectionLabelOf(connection: PortConnectionInfo | null, pairedPortName: string | null): string {
    if (connection?.cable) {
        return cableSummary(connection.cable);
    }

    if (!connection?.internal) {
        return 'Free';
    }

    return pairedPortName ? `Paired with ${ pairedPortName }` : 'Paired internally';
}


/** Both ends of an internal pairing are ports of the same object, so the peer can be named here. */
function pairedPortNameOf(
    connection: PortConnectionInfo | null,
    portId: number,
    namesByPortId: Map<number, string>
): string | null {
    const peerId = peerPortIdOf(connection?.internal ?? null, portId);

    return peerId == null ? null : namesByPortId.get(peerId) ?? null;
}


/** Empty values always sort last, so a table sorted by an optional column still starts with content. */
function compare(left: PortRow[keyof PortRow], right: PortRow[keyof PortRow]): number {
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


function isEmpty(value: PortRow[keyof PortRow]): boolean {
    return value === null || value === undefined || value === '';
}


function labelOf(optionId: number | null, labels: Map<string, string>): string | null {
    return optionId == null ? null : labels.get(String(optionId)) ?? null;
}
