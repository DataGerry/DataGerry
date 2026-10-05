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
    PatchPanelOverviewRow,
    PortSide,
    StandardOverviewRow
} from '../../../ports-overview/models/ports-overview.types';
import {
    CABLING_COLUMNS,
    CABLING_GEOMETRY,
    CABLING_ROUTING,
    CABLING_ROW_LIMIT,
    CABLING_WRAP_AFTER
} from '../constants/cabling.constants';
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
    CablingReveal,
    CablingRowLayout
} from '../models/cabling.types';
import {
    cableDescription,
    cableLabel,
    cableStroke,
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

type Density = 'compact' | 'detail';

type RouteKind = 'curve' | 'bracket' | 'passage' | 'hook';

interface Span {
    top: number;
    bottom: number;
}

interface ColumnFrame {
    left: number;
    /** Width of one sub-column; a wrapped column holds two. */
    slot: number;
    wrapped: boolean;
}

interface EdgeEnd {
    node: CablingNodeLayout;
    point: CablingPoint;
    side: CablingAnchorSide;
}

interface EdgePlan {
    edge: CablingEdge;
    from: EdgeEnd;
    to: EdgeEnd;
    kind: RouteKind;
}

interface Route {
    path: string;
    labelAt: CablingPoint;
}

/** A cable turning back around its own card: how far it bows out, and the level it runs back on. */
interface Hook {
    bulge: number;
    level: number;
}

interface Turn {
    key: string;
    end: EdgeEnd;
    other: EdgeEnd;
    below: boolean;
}

/** Where a cable's middle curve meets one end, past the hook that leads there from the port. */
interface Exit {
    point: CablingPoint;
    heading: number;
    out: string;
    back: string;
}

const {
    headerHeight, bodyPadding, footerHeight, emptyHeight, rowHeight, width, columnGap, subColumnGap, nodeGap, curveMin
} = CABLING_GEOMETRY;

/** Room kept between a routed cable and a card it passes. */
const CLEARANCE = 8;


/** Sizes and places every node. Positions come from how each node was revealed, never from the DOM. */
export function layoutCablingNodes(
    graph: CablingGraph,
    options: CablingDisplayOptions,
    expandedNodeIds: ReadonlySet<number>
): Map<number, CablingNodeLayout> {
    const drawnIds = new Set(graph.nodes.keys());
    const drawnCables = new Set(graph.edges.keys());
    const layouts = new Map<number, CablingNodeLayout>();

    graph.nodes.forEach((node, objectId) => layouts.set(objectId, nodeFrame(
        node,
        objectId === graph.focalId,
        graph.reveals.get(objectId),
        options,
        expandedNodeIds.has(objectId),
        drawnIds,
        drawnCables
    )));

    const columns = placeColumns(layouts);
    placeWithinColumns(graph, layouts, columns);

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


/** Routes each cable from port anchor to port anchor; a port facing away first turns back around its card. */
export function layoutCablingEdges(
    layouts: ReadonlyMap<number, CablingNodeLayout>,
    edges: Iterable<CablingEdge>
): CablingEdgeLayout[] {
    const cards = [...layouts.values()];
    const focal = cards.find((layout) => layout.focal) ?? null;
    const plans = [...edges]
        .map((edge) => planEdge(edge, layouts, focal))
        .filter((plan): plan is EdgePlan => !!plan);
    const reaches = bracketReaches(plans);
    const hooks = hookShapes(plans);

    return plans.map((plan): CablingEdgeLayout => {
        const route = routeEdge(plan, cards, reaches, hooks);
        const { edge, from, to } = plan;

        return {
            connectionId: edge.connection_id,
            path: route.path,
            from: from.point,
            to: to.point,
            labelAt: route.labelAt,
            label: cableLabel(edge.cable),
            description: cableDescription(edge.cable, edge.from, from.node.title, edge.to, to.node.title),
            stroke: cableStroke(edge.cable)
        };
    });
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
    reveal: CablingReveal | undefined,
    options: CablingDisplayOptions,
    expanded: boolean,
    drawnIds: ReadonlySet<number>,
    drawnCables: ReadonlySet<number>
): CablingNodeLayout {
    const density: Density = options.detail ? 'detail' : 'compact';
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


/** One column per hop, each as wide as its widest card; a crowded neighbours column holds two side by side. */
function placeColumns(layouts: Map<number, CablingNodeLayout>): Map<number, ColumnFrame> {
    const slots = new Map<number, number>();
    const counts = new Map<number, number>();

    layouts.forEach((layout) => {
        slots.set(layout.column, Math.max(slots.get(layout.column) ?? 0, layout.width));
        counts.set(layout.column, (counts.get(layout.column) ?? 0) + 1);
    });

    const frames = new Map<number, ColumnFrame>();
    let left = 0;

    [...slots.keys()].sort((first, second) => first - second).forEach((column) => {
        const slot = slots.get(column);
        const wrapped = column === CABLING_COLUMNS.neighbours && counts.get(column) > CABLING_WRAP_AFTER;

        frames.set(column, { left, slot, wrapped });
        left += (wrapped ? 2 * slot + subColumnGap : slot) + columnGap;
    });

    layouts.forEach((layout) => {
        const frame = frames.get(layout.column);
        layout.x = frame.left + (frame.slot - layout.width) / 2;
    });

    return frames;
}


/**
 * Places each node level with the port it was reached from, so a cable runs straight.
 *
 * Nodes are placed in the order they were revealed, one generation at a time, so a parent is always
 * placed before its children. Nodes revealed together are stacked and centred on where they wanted to
 * be; anything already standing in a column is stepped around.
 */
function placeWithinColumns(
    graph: CablingGraph,
    layouts: Map<number, CablingNodeLayout>,
    columns: ReadonlyMap<number, ColumnFrame>
): void {
    const placed = new Map<number, Span[]>();
    const batches = new Map<number, Map<number, number[]>>();

    layouts.forEach((layout, objectId) => {
        const generation = graph.reveals.get(objectId)?.generation ?? 0;
        const byColumn = batches.get(generation) ?? new Map<number, number[]>();

        byColumn.set(layout.column, [...(byColumn.get(layout.column) ?? []), objectId]);
        batches.set(generation, byColumn);
    });

    [...batches.keys()].sort((first, second) => first - second).forEach((generation) => {
        batches.get(generation).forEach((objectIds, column) => {
            const spans = placed.get(column) ?? [];
            const under = objectIds.filter((objectId) => sharesParentColumn(graph, layouts, objectId));
            const beside = objectIds.filter((objectId) => !under.includes(objectId));
            const frame = columns.get(column);

            if (frame?.wrapped) {
                placeWrapped(graph, layouts, beside, frame, spans);
            } else {
                placeBeside(graph, layouts, beside, spans);
            }

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


/** Alternates the cards between two sub-columns; each second sub-column cable runs level through a gap. */
function placeWrapped(
    graph: CablingGraph,
    layouts: ReadonlyMap<number, CablingNodeLayout>,
    objectIds: number[],
    frame: ColumnFrame,
    spans: Span[]
): void {
    const items = objectIds
        .map((objectId) => ({ objectId, layout: layouts.get(objectId), desired: desiredTop(graph, layouts, objectId) }))
        .sort((first, second) => first.desired - second.desired);

    if (!items.length) {
        return;
    }

    let innerCursor = -Infinity;
    let outerCursor = -Infinity;
    let innerBottom = -Infinity;

    const stacked = items.map((item, index) => {
        if (index % 2 === 0) {
            const top = Math.max(item.desired, innerCursor);
            innerBottom = top + item.layout.height;
            innerCursor = innerBottom + nodeGap;

            return top;
        }

        const anchor = anchorOffset(item.layout, graph.reveals.get(item.objectId)?.ownPortId ?? null);
        const passage = Math.max(innerBottom + nodeGap / 2, outerCursor + anchor);
        outerCursor = passage - anchor + item.layout.height + nodeGap;
        innerCursor = Math.max(innerCursor, passage + nodeGap / 2);

        return passage - anchor;
    });
    const shift = Math.round(items.reduce((sum, item, index) => sum + item.desired - stacked[index], 0) / items.length);

    items.forEach((item, index) => {
        if (index % 2 === 1) {
            item.layout.wrapped = true;
            item.layout.x = frame.left + frame.slot + subColumnGap + (frame.slot - item.layout.width) / 2;
        }

        placeAt(item.layout, stacked[index] + shift, spans);
    });
}


function placeAt(layout: CablingNodeLayout, top: number, spans: Span[]): void {
    layout.y = Math.round(top);
    spans.push({ top: layout.y, bottom: layout.y + layout.height });
}


/** Only the column limit puts a card in its parent's column; it then hangs below the parent. */
function sharesParentColumn(graph: CablingGraph, layouts: ReadonlyMap<number, CablingNodeLayout>, objectId: number): boolean {
    const parentId = graph.reveals.get(objectId)?.parentId;

    return parentId != null && parentId !== objectId && layouts.has(parentId)
        && layouts.get(parentId).column === layouts.get(objectId).column;
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


function planEdge(
    edge: CablingEdge,
    layouts: ReadonlyMap<number, CablingNodeLayout>,
    focal: CablingNodeLayout | null
): EdgePlan | null {
    const fromNode = layouts.get(edge.from.object_id);
    const toNode = layouts.get(edge.to.object_id);

    if (!fromNode || !toNode) {
        return null;
    }

    const fromSide = anchorSide(fromNode, edge.from.side, toNode, focal);
    const toSide = anchorSide(toNode, edge.to.side, fromNode, focal);
    const from = { node: fromNode, point: anchorPoint(fromNode, edge.from.port_id, fromSide), side: fromSide };
    const to = { node: toNode, point: anchorPoint(toNode, edge.to.port_id, toSide), side: toSide };

    return { edge, from, to, kind: routeKind(from, to) };
}


function routeKind(from: EdgeEnd, to: EdgeEnd): RouteKind {
    if (sharesColumn(from.node, to.node) && from.side === to.side) {
        return 'bracket';
    }

    if (passesWrap(from, to) || passesWrap(to, from)) {
        return 'passage';
    }

    return facesAway(from, to) || facesAway(to, from) ? 'hook' : 'curve';
}


function routeEdge(
    plan: EdgePlan,
    cards: CablingNodeLayout[],
    reaches: ReadonlyMap<number, number>,
    hooks: ReadonlyMap<string, Hook>
): Route {
    switch (plan.kind) {
        case 'bracket':
            return curveRoute(plan.from, plan.to, reaches.get(plan.edge.connection_id));
        case 'passage':
            return passageRoute(plan, cards);
        case 'hook':
            return hookRoute(plan, hooks);
        default:
            return curveRoute(plan.from, plan.to);
    }
}


/** Cables between two cards of one column loop out on the same side; the longer the loop, the wider it bows. */
function bracketReaches(plans: EdgePlan[]): Map<number, number> {
    const groups = new Map<string, EdgePlan[]>();

    plans.filter((plan) => plan.kind === 'bracket').forEach((plan) => {
        const key = `${ plan.from.node.column }:${ plan.from.node.wrapped }:${ plan.from.side }`;
        groups.set(key, [...(groups.get(key) ?? []), plan]);
    });

    const reaches = new Map<number, number>();

    groups.forEach((group) => group
        .sort((first, second) => span(first) - span(second))
        .forEach((plan, index) => reaches.set(
            plan.edge.connection_id,
            CABLING_ROUTING.bracketReach + index * CABLING_ROUTING.bracketStep
        )));

    return reaches;
}


function span(plan: EdgePlan): number {
    return Math.abs(plan.from.point.y - plan.to.point.y);
}


function curveRoute(from: EdgeEnd, to: EdgeEnd, reach?: number): Route {
    const pull = reach ?? Math.max(curveMin, Math.abs(to.point.x - from.point.x) / 2);
    const fromControl = { x: from.point.x + direction(from.side) * pull, y: from.point.y };
    const toControl = { x: to.point.x + direction(to.side) * pull, y: to.point.y };

    return {
        path: `M ${ from.point.x } ${ from.point.y } C ${ fromControl.x } ${ fromControl.y }, `
            + `${ toControl.x } ${ toControl.y }, ${ to.point.x } ${ to.point.y }`,
        labelAt: curveMiddle(from.point, fromControl, toControl, to.point)
    };
}


function curveMiddle(start: CablingPoint, startControl: CablingPoint, endControl: CablingPoint, end: CablingPoint): CablingPoint {
    return {
        x: (start.x + 3 * startControl.x + 3 * endControl.x + end.x) / 8,
        y: (start.y + 3 * startControl.y + 3 * endControl.y + end.y) / 8
    };
}


/** From the focal object to the second sub-column: level through a gap of the first, then into the port. */
function passageRoute(plan: EdgePlan, cards: CablingNodeLayout[]): Route {
    const [near, far] = passesWrap(plan.from, plan.to) ? [plan.from, plan.to] : [plan.to, plan.from];
    const inner = cards
        .filter((card) => card.column === far.node.column && !card.wrapped)
        .sort((first, second) => first.y - second.y);

    if (!inner.length) {
        return curveRoute(plan.from, plan.to);
    }

    const left = Math.min(...inner.map((card) => card.x));
    const right = Math.max(...inner.map((card) => card.x + card.width));
    const level = passageLevel(inner, far.point.y);
    const pull = Math.max(curveMin, (left - near.point.x) / 2);
    const bend = (far.point.x - right) / 2;

    return {
        path: `M ${ near.point.x } ${ near.point.y } C ${ near.point.x + pull } ${ near.point.y }, ${ left - pull } ${ level }, `
            + `${ left } ${ level } L ${ right } ${ level } C ${ right + bend } ${ level }, `
            + `${ far.point.x - bend } ${ far.point.y }, ${ far.point.x } ${ far.point.y }`,
        labelAt: { x: (near.point.x + left) / 2, y: (near.point.y + level) / 2 }
    };
}


/** The height nearest to `y` at which a cable clears every card of the first sub-column. */
function passageLevel(inner: CablingNodeLayout[], y: number): number {
    const gaps: Array<[number, number]> = [[-Infinity, inner[0].y - CLEARANCE]];

    inner.forEach((card, index) => gaps.push([
        card.y + card.height + CLEARANCE,
        index + 1 < inner.length ? inner[index + 1].y - CLEARANCE : Infinity
    ]));

    return gaps
        .filter(([top, bottom]) => top <= bottom)
        .map(([top, bottom]) => Math.min(Math.max(y, top), bottom))
        .reduce((best, level) => (Math.abs(level - y) < Math.abs(best - y) ? level : best));
}


/** Hooks running along one card edge nest: the row nearest the turn takes the tightest. */
function hookShapes(plans: EdgePlan[]): Map<string, Hook> {
    const groups = new Map<string, Turn[]>();

    plans
        .filter((plan) => plan.kind === 'hook')
        .flatMap((plan): Turn[] => [
            { key: `${ plan.edge.connection_id }:from`, end: plan.from, other: plan.to, below: false },
            { key: `${ plan.edge.connection_id }:to`, end: plan.to, other: plan.from, below: false }
        ])
        .filter((turn) => facesAway(turn.end, turn.other))
        .forEach((turn) => {
            const below = turnsBelow(turn.end, turn.other);
            const group = `${ turn.end.node.objectId }:${ below }`;

            groups.set(group, [...(groups.get(group) ?? []), { ...turn, below }]);
        });

    const hooks = new Map<string, Hook>();

    groups.forEach((group) => group
        .sort((first, second) => (first.below ? second.end.point.y - first.end.point.y : first.end.point.y - second.end.point.y))
        .forEach((turn, index) => {
            const { node } = turn.end;
            const clearance = nodeGap / 2 + index * CABLING_ROUTING.hookStep;

            hooks.set(turn.key, {
                bulge: CABLING_ROUTING.hookReach + index * CABLING_ROUTING.hookStep,
                level: turn.below ? node.y + node.height + clearance : node.y - clearance
            });
        }));

    return hooks;
}


/** Under the card when that is the shorter way round to the far end. */
function turnsBelow(end: EdgeEnd, other: EdgeEnd): boolean {
    const bottom = end.node.y + end.node.height;
    const top = end.node.y;

    return Math.abs(end.point.y - bottom) + Math.abs(other.point.y - bottom)
        <= Math.abs(end.point.y - top) + Math.abs(other.point.y - top);
}


/** Turns back around the card of a port facing away, then curves to the far end like any other cable. */
function hookRoute(plan: EdgePlan, hooks: ReadonlyMap<string, Hook>): Route {
    const start = exitFrom(plan.from, hooks.get(`${ plan.edge.connection_id }:from`));
    const end = exitFrom(plan.to, hooks.get(`${ plan.edge.connection_id }:to`));
    const pull = Math.max(curveMin, Math.abs(end.point.x - start.point.x) / 2);
    const startControl = { x: start.point.x + start.heading * pull, y: start.point.y };
    const endControl = { x: end.point.x + end.heading * pull, y: end.point.y };

    return {
        path: `M ${ plan.from.point.x } ${ plan.from.point.y } ${ start.out }`
            + `C ${ startControl.x } ${ startControl.y }, ${ endControl.x } ${ endControl.y }, ${ end.point.x } ${ end.point.y }`
            + end.back,
        labelAt: curveMiddle(start.point, startControl, endControl, end.point)
    };
}


/** Straight out of the port, or past the hook that turns back and runs under or over its card. */
function exitFrom(end: EdgeEnd, hook: Hook | undefined): Exit {
    const outwards = direction(end.side);

    if (!hook) {
        return { point: end.point, heading: outwards, out: '', back: '' };
    }

    const { x, y } = end.point;
    const bow = x + outwards * hook.bulge;
    const farEdge = x - outwards * end.node.width;

    return {
        point: { x: farEdge, y: hook.level },
        heading: -outwards,
        out: `C ${ bow } ${ y }, ${ bow } ${ hook.level }, ${ x } ${ hook.level } L ${ farEdge } ${ hook.level } `,
        back: ` L ${ x } ${ hook.level } C ${ bow } ${ hook.level }, ${ bow } ${ y }, ${ x } ${ y }`
    };
}


/** From the focal object's right face to a card of a second sub-column. */
function passesWrap(near: EdgeEnd, far: EdgeEnd): boolean {
    return near.node.focal && near.side === 'right' && far.node.wrapped;
}


function sharesColumn(first: CablingNodeLayout, second: CablingNodeLayout): boolean {
    return first.column === second.column && first.wrapped === second.wrapped;
}


/** The port's face points away from the far end, so the cable has to turn back around its card. */
function facesAway(end: EdgeEnd, other: EdgeEnd): boolean {
    return direction(end.side) * (other.point.x - end.point.x) <= 0;
}


/** A panel's front is its left face and its rear the right; a plain port faces its peer, or outwards when level. */
function anchorSide(
    layout: CablingNodeLayout,
    side: PortSide | null,
    peer: CablingNodeLayout,
    focal: CablingNodeLayout | null
): CablingAnchorSide {
    if (layout.patchPanel && side === PortSide.FRONT) {
        return 'left';
    }

    if (layout.patchPanel && side === PortSide.REAR) {
        return 'right';
    }

    const own = centre(layout);
    const other = centre(peer);

    if (own !== other) {
        return other < own ? 'left' : 'right';
    }

    return focal && own < centre(focal) ? 'left' : 'right';
}


function centre(layout: CablingNodeLayout): number {
    return layout.x + layout.width / 2;
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
