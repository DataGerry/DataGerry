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
import { CablingEdgePlan } from '../models/cabling-routing.types';
import {
    CablingBounds,
    CablingDisplayOptions,
    CablingEdge,
    CablingEdgeLayout,
    CablingGraph,
    CablingNodeLayout,
    CablingPoint
} from '../models/cabling.types';
import { planEdge } from './cabling-edge-plan.util';
import { cableDescription, cableLabel, cableStroke } from './cabling-format.util';
import { nodeFrame } from './cabling-node-frame.util';
import { placeCablingNodes } from './cabling-placement.util';
import { bracketReaches, hookShapes, routeEdge } from './cabling-route.util';
/* ------------------------------------------------------------------------------------------------------------------ */

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

    placeCablingNodes(graph, layouts);

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
        .filter((plan): plan is CablingEdgePlan => !!plan);
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
