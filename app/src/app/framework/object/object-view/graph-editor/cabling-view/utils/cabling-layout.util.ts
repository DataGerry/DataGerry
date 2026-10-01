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
import { PortDeviceKind } from '../../../ports-overview/models/port-bulk.types';
import {
    PatchPanelOverviewRow,
    PortSide,
    StandardOverviewRow
} from '../../../ports-overview/models/ports-overview.types';
import { CABLING_GEOMETRY, CABLING_ROW_LIMIT } from '../constants/cabling.constants';
import {
    CablingAnchorSide,
    CablingBounds,
    CablingDisplayOptions,
    CablingEdge,
    CablingEdgeLayout,
    CablingGraph,
    CablingNode,
    CablingNodeLayout,
    CablingPoint,
    CablingRowLayout
} from '../models/cabling.types';
import {
    cableDescription,
    cableLabel,
    cableStroke,
    hasCable,
    isRestrictedNode,
    nodeAccent,
    nodeIcon,
    nodeSubtitle,
    nodeTitle,
    portView
} from './cabling-format.util';
import { isPanelRow } from './cabling-graph.util';
/* ------------------------------------------------------------------------------------------------------------------ */

type Density = 'compact' | 'detail';

interface Span {
    top: number;
    bottom: number;
}

const { headerHeight, bodyPadding, footerHeight, emptyHeight, rowHeight, width, columnGap, nodeGap, curveMin } =
    CABLING_GEOMETRY;


/** Sizes and places every node. Positions come from how each node was revealed, never from the DOM. */
export function layoutCablingNodes(
    graph: CablingGraph,
    options: CablingDisplayOptions,
    expandedNodeIds: ReadonlySet<number>
): Map<number, CablingNodeLayout> {
    const drawnIds = new Set(graph.nodes.keys());
    const layouts = new Map<number, CablingNodeLayout>();

    graph.nodes.forEach((node, objectId) => layouts.set(objectId, nodeFrame(
        node, objectId === graph.focalId, options, expandedNodeIds.has(objectId), drawnIds
    )));

    placeColumns(graph, layouts);
    placeWithinColumns(graph, layouts);

    return layouts;
}


/** Moves the nodes the user dragged; everything else keeps its computed place. */
export function offsetCablingNodes(
    layouts: ReadonlyMap<number, CablingNodeLayout>,
    offsets: ReadonlyMap<number, CablingPoint>
): Map<number, CablingNodeLayout> {
    const moved = new Map<number, CablingNodeLayout>();

    layouts.forEach((layout, objectId) => {
        const offset = offsets.get(objectId);
        moved.set(objectId, offset ? { ...layout, x: layout.x + offset.x, y: layout.y + offset.y } : layout);
    });

    return moved;
}


/** Routes each cable from port anchor to port anchor, leaving each card on the side facing its peer. */
export function layoutCablingEdges(
    layouts: ReadonlyMap<number, CablingNodeLayout>,
    edges: Iterable<CablingEdge>
): CablingEdgeLayout[] {
    const routed: CablingEdgeLayout[] = [];

    for (const edge of edges) {
        const fromNode = layouts.get(edge.from.object_id);
        const toNode = layouts.get(edge.to.object_id);

        if (!fromNode || !toNode) {
            continue;
        }

        const fromSide = anchorSide(fromNode, edge.from.side, toNode);
        const toSide = anchorSide(toNode, edge.to.side, fromNode);
        const from = anchorPoint(fromNode, edge.from.port_id, fromSide);
        const to = anchorPoint(toNode, edge.to.port_id, toSide);
        const reach = Math.max(curveMin, Math.abs(to.x - from.x) / 2);
        const fromControl = { x: from.x + direction(fromSide) * reach, y: from.y };
        const toControl = { x: to.x + direction(toSide) * reach, y: to.y };

        routed.push({
            connectionId: edge.connection_id,
            path: `M ${ from.x } ${ from.y } C ${ fromControl.x } ${ fromControl.y }, `
                + `${ toControl.x } ${ toControl.y }, ${ to.x } ${ to.y }`,
            from,
            to,
            labelAt: {
                x: (from.x + 3 * fromControl.x + 3 * toControl.x + to.x) / 8,
                y: (from.y + 3 * fromControl.y + 3 * toControl.y + to.y) / 8
            },
            label: cableLabel(edge.cable),
            description: cableDescription(edge.cable, edge.from, fromNode.title, edge.to, toNode.title),
            stroke: cableStroke(edge.cable)
        });
    }

    return routed;
}


export function cablingBounds(layouts: Iterable<CablingNodeLayout>): CablingBounds | null {
    let bounds: CablingBounds | null = null;

    for (const layout of layouts) {
        bounds = {
            minX: Math.min(bounds?.minX ?? Infinity, layout.x),
            minY: Math.min(bounds?.minY ?? Infinity, layout.y),
            maxX: Math.max(bounds?.maxX ?? -Infinity, layout.x + layout.width),
            maxY: Math.max(bounds?.maxY ?? -Infinity, layout.y + layout.height)
        };
    }

    return bounds;
}


/** Where a port's cable meets the card; a port without a row of its own uses the fallback. */
export function anchorOffset(layout: CablingNodeLayout, portId: number | null): number {
    return portId == null ? layout.defaultAnchor : (layout.anchors.get(portId) ?? layout.defaultAnchor);
}

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

function nodeFrame(
    node: CablingNode,
    focal: boolean,
    options: CablingDisplayOptions,
    expanded: boolean,
    drawnIds: ReadonlySet<number>
): CablingNodeLayout {
    const density: Density = options.detail ? 'detail' : 'compact';
    const restricted = isRestrictedNode(node);
    const patchPanel = !restricted && node.device_kind === PortDeviceKind.PATCH_PANEL;
    const kind = patchPanel ? 'panel' : 'standard';
    const frame: CablingNodeLayout = {
        objectId: node.object_id,
        focal,
        restricted,
        patchPanel,
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
    const limit = CABLING_ROW_LIMIT[density];
    const visibleRows = expanded ? shownRows : shownRows.slice(0, limit);
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

    const footer = shownRows.length > limit
        ? { top: cursor, hiddenPorts: portsIn(shownRows.slice(visibleRows.length)), expanded }
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


/** One column per hop from the focal object, each as wide as its widest card. */
function placeColumns(graph: CablingGraph, layouts: Map<number, CablingNodeLayout>): void {
    const widths = new Map<number, number>();

    layouts.forEach((layout, objectId) => {
        const column = columnOf(graph, objectId);
        widths.set(column, Math.max(widths.get(column) ?? 0, layout.width));
    });

    const lefts = new Map<number, number>();
    let left = 0;

    [...widths.keys()].sort((first, second) => first - second).forEach((column) => {
        lefts.set(column, left);
        left += widths.get(column) + columnGap;
    });

    layouts.forEach((layout, objectId) => {
        const column = columnOf(graph, objectId);
        layout.x = lefts.get(column) + (widths.get(column) - layout.width) / 2;
    });
}


/**
 * Places each node level with the port it was reached from, so a cable runs straight.
 *
 * Nodes are placed in the order they were revealed, one generation at a time, so a parent is always
 * placed before its children. Nodes revealed together are stacked and centred on where they wanted to
 * be; anything already standing in a column is stepped around.
 */
function placeWithinColumns(graph: CablingGraph, layouts: Map<number, CablingNodeLayout>): void {
    const placed = new Map<number, Span[]>();
    const batches = new Map<number, Map<number, number[]>>();

    layouts.forEach((_layout, objectId) => {
        const generation = graph.reveals.get(objectId)?.generation ?? 0;
        const column = columnOf(graph, objectId);
        const byColumn = batches.get(generation) ?? new Map<number, number[]>();

        byColumn.set(column, [...(byColumn.get(column) ?? []), objectId]);
        batches.set(generation, byColumn);
    });

    [...batches.keys()].sort((first, second) => first - second).forEach((generation) => {
        batches.get(generation).forEach((objectIds, column) => {
            const spans = placed.get(column) ?? [];
            const under = objectIds.filter((objectId) => sharesParentColumn(graph, layouts, objectId));

            placeBeside(graph, layouts, objectIds.filter((objectId) => !under.includes(objectId)), spans);

            under.forEach((objectId) => {
                const layout = layouts.get(objectId);
                const parent = layouts.get(graph.reveals.get(objectId).parentId);

                placeAt(layout, freeTop(parent.y + parent.height + nodeGap, layout.height, spans, true), spans);
            });

            placed.set(column, spans);
        });
    });
}


/** Cards revealed together beside their parents: stacked, centred on where they wanted to be, then stepped clear. */
function placeBeside(
    graph: CablingGraph,
    layouts: ReadonlyMap<number, CablingNodeLayout>,
    objectIds: number[],
    spans: Span[]
): void {
    const items = objectIds
        .map((objectId) => ({ layout: layouts.get(objectId), desired: desiredTop(graph, layouts, objectId) }))
        .sort((first, second) => first.desired - second.desired);

    if (!items.length) {
        return;
    }

    let cursor = -Infinity;
    const stacked = items.map((item) => {
        const top = Math.max(item.desired, cursor);
        cursor = top + item.layout.height + nodeGap;

        return top;
    });
    const shift = items.reduce((sum, item, index) => sum + item.desired - stacked[index], 0) / items.length;

    items.forEach((item, index) => placeAt(item.layout, freeTop(stacked[index] + shift, item.layout.height, spans), spans));
}


function placeAt(layout: CablingNodeLayout, top: number, spans: Span[]): void {
    layout.y = Math.round(top);
    spans.push({ top: layout.y, bottom: layout.y + layout.height });
}


/** Only the column limit puts a card in its parent's column; it then hangs below the parent. */
function sharesParentColumn(graph: CablingGraph, layouts: ReadonlyMap<number, CablingNodeLayout>, objectId: number): boolean {
    const parentId = graph.reveals.get(objectId)?.parentId;

    return parentId != null && parentId !== objectId && layouts.has(parentId)
        && columnOf(graph, parentId) === columnOf(graph, objectId);
}


function desiredTop(graph: CablingGraph, layouts: ReadonlyMap<number, CablingNodeLayout>, objectId: number): number {
    const reveal = graph.reveals.get(objectId);
    const parent = reveal?.parentId != null && reveal.parentId !== objectId ? layouts.get(reveal.parentId) : undefined;

    if (!parent) {
        return 0;
    }

    return parent.y + anchorOffset(parent, reveal.parentPortId) - anchorOffset(layouts.get(objectId), reveal.ownPortId);
}


/** The free top nearest to the wanted one, or the nearest below it. Below the lowest node is always free. */
function freeTop(desired: number, height: number, spans: Span[], downwardOnly = false): number {
    const clashes = (top: number) => spans.some((span) => top < span.bottom + nodeGap && top + height + nodeGap > span.top);

    if (!clashes(desired)) {
        return desired;
    }

    return spans
        .flatMap((span) => [span.bottom + nodeGap, span.top - nodeGap - height])
        .filter((top) => !clashes(top) && (!downwardOnly || top >= desired))
        .reduce((best, top) => (Math.abs(top - desired) < Math.abs(best - desired) ? top : best));
}


function columnOf(graph: CablingGraph, objectId: number): number {
    return graph.reveals.get(objectId)?.column ?? 0;
}


/** A panel's front is its left face and its rear the right; a plain port faces its peer. */
function anchorSide(layout: CablingNodeLayout, side: PortSide | null, peer: CablingNodeLayout): CablingAnchorSide {
    if (layout.patchPanel && side === PortSide.FRONT) {
        return 'left';
    }

    if (layout.patchPanel && side === PortSide.REAR) {
        return 'right';
    }

    return peer.x + peer.width / 2 < layout.x + layout.width / 2 ? 'left' : 'right';
}


function anchorPoint(layout: CablingNodeLayout, portId: number, side: CablingAnchorSide): CablingPoint {
    return {
        x: side === 'left' ? layout.x : layout.x + layout.width,
        y: layout.y + anchorOffset(layout, portId)
    };
}


function direction(side: CablingAnchorSide): number {
    return side === 'left' ? -1 : 1;
}
