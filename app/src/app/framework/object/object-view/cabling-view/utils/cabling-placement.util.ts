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
import { CABLING_COLUMNS, CABLING_GEOMETRY, CABLING_WRAP_AFTER } from '../constants/cabling.constants';
import { CablingColumnFrame, CablingSpan, CablingStepDirection } from '../models/cabling-placement.types';
import { CablingGraph, CablingNodeLayout } from '../models/cabling.types';
import { anchorOffset } from './cabling-node-frame.util';
/* ------------------------------------------------------------------------------------------------------------------ */

const { columnGap, subColumnGap, nodeGap } = CABLING_GEOMETRY;


/** Positions every sized node: first its column, then its place within that column. */
export function placeCablingNodes(graph: CablingGraph, layouts: Map<number, CablingNodeLayout>): void {
    placeWithinColumns(graph, layouts, placeColumns(layouts));
}

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

/** One column per hop, each as wide as its widest card; a crowded neighbours column holds two side by side. */
function placeColumns(layouts: Map<number, CablingNodeLayout>): Map<number, CablingColumnFrame> {
    const slots = new Map<number, number>();
    const counts = new Map<number, number>();

    layouts.forEach((layout) => {
        slots.set(layout.column, Math.max(slots.get(layout.column) ?? 0, layout.width));
        counts.set(layout.column, (counts.get(layout.column) ?? 0) + 1);
    });

    const frames = new Map<number, CablingColumnFrame>();
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
    columns: ReadonlyMap<number, CablingColumnFrame>
): void {
    const placed = new Map<number, CablingSpan[]>();
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
            const stacked = objectIds.filter((objectId) => sharesParentColumn(graph, layouts, objectId));
            const above = stacked.filter((objectId) => parentOf(graph, layouts, objectId).focal);
            const under = stacked.filter((objectId) => !above.includes(objectId));
            const beside = objectIds.filter((objectId) => !stacked.includes(objectId));
            const frame = columns.get(column);

            // Only the first batch alternates; a card revealed later steps clear like anywhere else.
            if (frame?.wrapped && !spans.length) {
                placeWrapped(graph, layouts, beside, frame, spans);
            } else {
                placeBeside(graph, layouts, beside, spans);
            }

            placeAboveFocal(graph, layouts, above, spans);

            under.forEach((objectId) => {
                const layout = layouts.get(objectId);
                const parent = parentOf(graph, layouts, objectId);

                placeAt(layout, freeTop(parent.y + parent.height + nodeGap, layout.height, spans, 'down'), spans);
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
    spans: CablingSpan[]
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
    frame: CablingColumnFrame,
    spans: CablingSpan[]
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


/** Panels cabled to the focal object stack up from it; the one on its topmost port stands nearest, so brackets nest. */
function placeAboveFocal(
    graph: CablingGraph,
    layouts: ReadonlyMap<number, CablingNodeLayout>,
    objectIds: number[],
    spans: CablingSpan[]
): void {
    const portTop = (objectId: number) => anchorOffset(parentOf(graph, layouts, objectId), graph.reveals.get(objectId).parentPortId);

    [...objectIds].sort((first, second) => portTop(first) - portTop(second)).forEach((objectId) => {
        const layout = layouts.get(objectId);
        const focal = parentOf(graph, layouts, objectId);

        placeAt(layout, freeTop(focal.y - nodeGap - layout.height, layout.height, spans, 'up'), spans);
    });
}


function placeAt(layout: CablingNodeLayout, top: number, spans: CablingSpan[]): void {
    layout.y = Math.round(top);
    spans.push({ top: layout.y, bottom: layout.y + layout.height });
}


/** A panel cabled to a plain focal object stands above it; past the column limit a card hangs below its parent. */
function sharesParentColumn(graph: CablingGraph, layouts: ReadonlyMap<number, CablingNodeLayout>, objectId: number): boolean {
    const parentId = graph.reveals.get(objectId)?.parentId;

    return parentId != null && parentId !== objectId && layouts.has(parentId)
        && layouts.get(parentId).column === layouts.get(objectId).column;
}


function parentOf(graph: CablingGraph, layouts: ReadonlyMap<number, CablingNodeLayout>, objectId: number): CablingNodeLayout {
    return layouts.get(graph.reveals.get(objectId).parentId);
}


function desiredTop(graph: CablingGraph, layouts: ReadonlyMap<number, CablingNodeLayout>, objectId: number): number {
    const reveal = graph.reveals.get(objectId);
    const parent = reveal?.parentId != null && reveal.parentId !== objectId ? layouts.get(reveal.parentId) : undefined;

    if (!parent) {
        return 0;
    }

    return parent.y + anchorOffset(parent, reveal.parentPortId) - anchorOffset(layouts.get(objectId), reveal.ownPortId);
}


/** The free top nearest to the wanted one, optionally only above or below it. Past the outermost nodes is always free. */
function freeTop(desired: number, height: number, spans: CablingSpan[], only?: CablingStepDirection): number {
    const clashes = (top: number) => spans.some((span) => top < span.bottom + nodeGap && top + height + nodeGap > span.top);

    if (!clashes(desired)) {
        return desired;
    }

    return spans
        .flatMap((span) => [span.bottom + nodeGap, span.top - nodeGap - height])
        .filter((top) => !clashes(top) && isOnSide(top, desired, only))
        .reduce((best, top) => (Math.abs(top - desired) < Math.abs(best - desired) ? top : best));
}


function isOnSide(top: number, desired: number, only?: CablingStepDirection): boolean {
    if (only === 'up') {
        return top <= desired;
    }

    return only !== 'down' || top >= desired;
}
