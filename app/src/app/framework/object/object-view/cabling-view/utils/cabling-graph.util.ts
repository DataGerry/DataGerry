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
    OverviewPort,
    PatchPanelOverviewRow,
    PortSide,
    StandardOverviewRow
} from '../../ports-overview/models/ports-overview.types';
import {
    CablingEdge,
    CablingEnd,
    CablingGraph,
    CablingNode,
    CablingResponse,
    CablingReveal
} from '../models/cabling.types';
import { CABLING_COLUMNS } from '../constants/cabling.constants';
import { hasCable, isPatchPanelNode, isRestrictedNode } from './cabling-format.util';
/* ------------------------------------------------------------------------------------------------------------------ */

export const EMPTY_CABLING_GRAPH: CablingGraph = {
    focalId: null,
    nodes: new Map(),
    reveals: new Map(),
    edges: new Map()
};

const FOCAL_REVEAL: CablingReveal = {
    parentId: null,
    parentPortId: null,
    ownPortId: null,
    column: CABLING_COLUMNS.focal,
    generation: 0
};


export function isPanelRow(row: StandardOverviewRow | PatchPanelOverviewRow): row is PatchPanelOverviewRow {
    return 'front' in row || 'rear' in row;
}


/** Every port of a readable node, both faces of a panel row included. */
export function nodePorts(node: CablingNode): OverviewPort[] {
    if (isRestrictedNode(node)) {
        return [];
    }

    return (node.rows ?? []).flatMap((row) => (isPanelRow(row) ? [row.front, row.rear] : [row.port]))
        .filter((port): port is OverviewPort => !!port);
}


/**
 * A panel keeps what is cabled to its front on its left and to its rear on its right. A panel reached from a
 * plain device steps one column back towards the focal object, where there is room. Anything else flows away.
 */
export function revealColumn(parent: CablingReveal, parentFace: PortSide | null, patchPanel: boolean): number {
    if (parentFace) {
        return withinColumns(parent.column, parent.column + faceStep(parentFace));
    }

    if (patchPanel) {
        return parent.column - Math.sign(parent.column);
    }

    if (parent.column === CABLING_COLUMNS.focal) {
        return CABLING_COLUMNS.neighbours;
    }

    return withinColumns(parent.column, parent.column + Math.sign(parent.column));
}


/** The first ring: the focal object, every object one cable away, and the focal object's own cables. */
export function graphFromRing(response: CablingResponse): CablingGraph {
    const focalId = response.focal_object_id;
    const nodes = new Map<number, CablingNode>();
    const focal = response.nodes.find((node) => node.object_id === focalId);

    if (focal) {
        nodes.set(focalId, focal);
    }

    response.nodes.forEach((node) => {
        if (!nodes.has(node.object_id)) {
            nodes.set(node.object_id, node);
        }
    });

    const edges = focalEdges(nodes, focalId, response.edges);
    const reveals = new Map<number, CablingReveal>();

    reveals.set(focalId, FOCAL_REVEAL);

    nodes.forEach((node, objectId) => {
        if (!reveals.has(objectId)) {
            const edge = edgeBetween(edges.values(), focalId, objectId);
            reveals.set(objectId, revealBeside(nodes, reveals, focalId, edge ? endOn(edge, focalId) : null, edge, node));
        }
    });

    return { focalId, nodes, reveals, edges };
}


/** Adds the followed cable, and its far object unless drawn; a drawn node keeps its place and takes the fresher rows. */
export function graphWithExpansion(graph: CablingGraph, response: CablingResponse, portId: number): CablingGraph {
    const parentId = response.focal_object_id;
    const nodes = new Map(graph.nodes);
    const reveals = new Map(graph.reveals);
    const edges = new Map(graph.edges);
    const revealed = response.nodes.filter((node) => !nodes.has(node.object_id));
    const followed = response.edges.find((edge) => endOnPort(edge, portId) !== null) ?? null;

    response.nodes.forEach((node) => nodes.set(node.object_id, node));

    if (followed && isDrawn(nodes, followed)) {
        edges.set(followed.connection_id, followed);
    }

    revealed.forEach((node) => {
        const parentEnd = followed ? endOnPort(followed, portId) : null;

        reveals.set(node.object_id, revealBeside(nodes, reveals, parentId, parentEnd, followed, node));
    });

    return { ...graph, nodes, reveals, edges };
}


/** The objects an expansion would add; used to tell a new node from one already on the canvas. */
export function revealedObjectIds(graph: CablingGraph, response: CablingResponse): number[] {
    return response.nodes.map((node) => node.object_id).filter((objectId) => !graph.nodes.has(objectId));
}

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

function revealBeside(
    nodes: ReadonlyMap<number, CablingNode>,
    reveals: ReadonlyMap<number, CablingReveal>,
    parentId: number,
    parentEnd: CablingEnd | null,
    edge: CablingEdge | null | undefined,
    node: CablingNode
): CablingReveal {
    const parent = reveals.get(parentId) ?? FOCAL_REVEAL;
    const ownEnd = edge && parentEnd ? otherEnd(edge, parentEnd) : null;

    return {
        parentId,
        parentPortId: parentEnd?.port_id ?? null,
        ownPortId: ownEnd?.port_id ?? null,
        column: revealColumn(parent, panelFace(nodes.get(parentId), parentEnd), isPatchPanelNode(node)),
        generation: parent.generation + 1
    };
}


/** The panel face a cable meets; null on a plain device. */
function panelFace(node: CablingNode | undefined, end: CablingEnd | null): PortSide | null {
    const side = end?.side;

    return isPatchPanelNode(node) && (side === PortSide.FRONT || side === PortSide.REAR) ? side : null;
}


/** A panel's front faces left, its rear right. */
function faceStep(face: PortSide): number {
    return face === PortSide.FRONT ? -1 : 1;
}


/** Past the outer columns a card stays in its parent's column. */
function withinColumns(parentColumn: number, column: number): number {
    return column < CABLING_COLUMNS.first || column > CABLING_COLUMNS.last ? parentColumn : column;
}


/** Only the focal object's cables; one between two neighbours waits until the user follows it. */
function focalEdges(
    nodes: ReadonlyMap<number, CablingNode>,
    focalId: number,
    responseEdges: CablingEdge[]
): Map<number, CablingEdge> {
    const edges = new Map<number, CablingEdge>();
    const focal = nodes.get(focalId);

    responseEdges
        .filter((edge) => endsOn(edge, focalId) && isDrawn(nodes, edge))
        .forEach((edge) => edges.set(edge.connection_id, edge));

    // A cable the edge list misses is still named by the focal object's rows.
    (focal ? nodePorts(focal) : []).forEach((port) => {
        const connectionId = port.cable_connection_id;
        const farObjectId = port.connected_object?.object_id;

        if (hasCable(port) && farObjectId != null && port.connected_port && nodes.has(farObjectId)
            && !edges.has(connectionId)) {
            edges.set(connectionId, edgeFromPort(focalId, port));
        }
    });

    return edges;
}


function isDrawn(nodes: ReadonlyMap<number, CablingNode>, edge: CablingEdge): boolean {
    return [edge.from, edge.to].every((end) => end?.object_id != null && nodes.has(end.object_id));
}


function endsOn(edge: CablingEdge, objectId: number): boolean {
    return edge.from.object_id === objectId || edge.to.object_id === objectId;
}


function edgeFromPort(objectId: number, port: OverviewPort): CablingEdge {
    const near: CablingEnd = { object_id: objectId, port_id: port.port_id, port_name: port.name, side: port.side };
    const far: CablingEnd = {
        object_id: port.connected_object.object_id,
        port_id: port.connected_port.port_id,
        port_name: port.connected_port.name ?? null,
        side: port.connected_port.side ?? null
    };
    const [from, to] = near.port_id < far.port_id ? [near, far] : [far, near];

    return { connection_id: port.cable_connection_id, from, to, cable: port.cable ?? null };
}


function edgeBetween(edges: Iterable<CablingEdge>, first: number, second: number): CablingEdge | null {
    for (const edge of edges) {
        const ends = [edge.from.object_id, edge.to.object_id];

        if (ends.includes(first) && ends.includes(second)) {
            return edge;
        }
    }

    return null;
}


function endOn(edge: CablingEdge, objectId: number): CablingEnd {
    return edge.from.object_id === objectId ? edge.from : edge.to;
}


function endOnPort(edge: CablingEdge, portId: number): CablingEnd | null {
    if (edge.from.port_id === portId) {
        return edge.from;
    }

    return edge.to.port_id === portId ? edge.to : null;
}


function otherEnd(edge: CablingEdge, end: CablingEnd): CablingEnd {
    return end === edge.from ? edge.to : edge.from;
}
