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
import { PatchPanelOverviewRow, StandardOverviewRow } from '../../ports-overview/models/ports-overview.types';
import { CABLING_COLUMNS, CABLING_GEOMETRY, CABLING_ROW_LIMIT } from '../constants/cabling.constants';
import {
    CablingDisplayOptions,
    CablingNode,
    CablingNodeLayout,
    CablingReveal,
    CablingRowLayout
} from '../models/cabling.types';
import {
    hasCable,
    isPatchPanelNode,
    isRestrictedNode,
    nodeAccent,
    nodeIcon,
    nodeSubtitle,
    nodeTitle,
    portView
} from './cabling-format.util';
import { isPanelRow } from './cabling-graph.util';
/* ------------------------------------------------------------------------------------------------------------------ */

const { headerHeight, bodyPadding, footerHeight, emptyHeight, rowHeight, width } = CABLING_GEOMETRY;


/** Sizes one node card and lays out its rows; its position is left to the placement step. */
export function nodeFrame(
    node: CablingNode,
    focal: boolean,
    reveal: CablingReveal | undefined,
    options: CablingDisplayOptions,
    expanded: boolean,
    drawnIds: ReadonlySet<number>,
    drawnCables: ReadonlySet<number>
): CablingNodeLayout {
    const density = options.detail ? 'detail' : 'compact';
    const restricted = isRestrictedNode(node);
    const patchPanel = isPatchPanelNode(node);
    const kind = patchPanel ? 'panel' : 'standard';
    const frame: CablingNodeLayout = {
        objectId: node.object_id,
        focal,
        restricted,
        patchPanel,
        column: reveal?.column ?? CABLING_COLUMNS.focal,
        wrapped: false,
        title: nodeTitle(node),
        subtitle: nodeSubtitle(node),
        icon: nodeIcon(node),
        accent: nodeAccent(node),
        portCount: restricted ? 0 : (node.port_count ?? 0),
        x: 0,
        y: 0,
        width: width[kind][density],
        height: headerHeight,
        rows: [],
        footer: null,
        emptyMessage: null,
        anchors: new Map(),
        defaultAnchor: headerHeight / 2
    };

    if (restricted || !options.showPorts) {
        return frame;
    }

    const allRows = node.rows ?? [];
    const shownRows = options.onlyConnected ? allRows.filter(rowHasCable) : allRows;
    const foldedRows = restingRows(shownRows, drawnCables, CABLING_ROW_LIMIT[density]);
    const visibleRows = expanded ? shownRows : foldedRows;
    const height = rowHeight[kind][density];
    const anchors = new Map<number, number>();
    let cursor = headerHeight + bodyPadding;

    const rows = visibleRows.map((row, index): CablingRowLayout => {
        const layout = rowLayout(row, index, cursor, height, drawnIds);

        [layout.port, layout.front, layout.rear]
            .filter((port) => !!port)
            .forEach((port) => anchors.set(port.portId, cursor + height / 2));
        cursor += height;

        return layout;
    });

    const emptyMessage = shownRows.length ? null : (allRows.length ? 'No connected ports' : 'No ports');

    if (emptyMessage) {
        cursor += emptyHeight;
    }

    const footer = foldedRows.length < shownRows.length
        ? { top: cursor, hiddenPorts: portsIn(shownRows.filter((row) => !foldedRows.includes(row))), expanded }
        : null;

    if (footer) {
        cursor += footerHeight;
    }

    return {
        ...frame,
        height: cursor + bodyPadding,
        rows,
        footer,
        emptyMessage,
        anchors,
        // A cable on a folded port meets the card at the line that unfolds it.
        defaultAnchor: footer ? footer.top + footerHeight / 2 : headerHeight / 2
    };
}


/** Where a port's cable meets the card; a port without a row of its own uses the fallback. */
export function anchorOffset(layout: CablingNodeLayout, portId: number | null): number {
    return portId == null ? layout.defaultAnchor : (layout.anchors.get(portId) ?? layout.defaultAnchor);
}

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

/** The rows a folded card keeps, at most `limit`; rows whose cable is drawn take the places first. */
function restingRows(
    rows: Array<StandardOverviewRow | PatchPanelOverviewRow>,
    drawnCables: ReadonlySet<number>,
    limit: number
): Array<StandardOverviewRow | PatchPanelOverviewRow> {
    const drawn = rows.filter((row) => rowCables(row).some((connectionId) => drawnCables.has(connectionId)));
    const kept = new Set([...drawn, ...rows.filter((row) => !drawn.includes(row))].slice(0, limit));

    return rows.filter((row) => kept.has(row));
}


function rowCables(row: StandardOverviewRow | PatchPanelOverviewRow): number[] {
    const ports = isPanelRow(row) ? [row.front, row.rear] : [row.port];

    return ports.map((port) => port?.cable_connection_id).filter((connectionId): connectionId is number => connectionId != null);
}


function rowLayout(
    row: StandardOverviewRow | PatchPanelOverviewRow,
    index: number,
    top: number,
    height: number,
    drawnIds: ReadonlySet<number>
): CablingRowLayout {
    if (isPanelRow(row)) {
        const front = row.front ? portView(row.front, drawnIds) : null;
        const rear = row.rear ? portView(row.rear, drawnIds) : null;

        return {
            key: `pair-${ front?.portId ?? 'none' }-${ rear?.portId ?? 'none' }-${ index }`,
            top,
            height,
            port: null,
            front,
            rear,
            paired: row.paired === true
        };
    }

    const port = row.port ? portView(row.port, drawnIds) : null;

    return { key: `port-${ port?.portId ?? index }`, top, height, port, front: null, rear: null, paired: false };
}


function rowHasCable(row: StandardOverviewRow | PatchPanelOverviewRow): boolean {
    return isPanelRow(row) ? hasCable(row.front) || hasCable(row.rear) : hasCable(row.port);
}


function portsIn(rows: Array<StandardOverviewRow | PatchPanelOverviewRow>): number {
    return rows.reduce((count, row) => count + (isPanelRow(row)
        ? Number(!!row.front) + Number(!!row.rear)
        : Number(!!row.port)), 0);
}
