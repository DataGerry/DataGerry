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
import { CablingSelection, CablingTrace } from '../models/cabling-spotlight.types';
import { CablingEdge, CablingGraph, CablingReveal } from '../models/cabling.types';
import { isPatchPanelNode } from './cabling-format.util';
/* ------------------------------------------------------------------------------------------------------------------ */

/** The picked cable, both its ends, and every cable on the reveal chain from its nearer end back to the focal object. */
export function spotlightTrace(graph: CablingGraph, selection: CablingSelection): CablingTrace {
    const connectionIds = new Set([selection.connectionId]);
    const portIds = new Set(selection.portId == null ? [] : [selection.portId]);
    const picked = graph.edges.get(selection.connectionId);

    if (!picked || selection.portId == null) {
        return { connectionIds, portIds };
    }

    [picked, ...revealChain(graph, traceStart(graph, picked, selection.objectId))].forEach((edge) => {
        connectionIds.add(edge.connection_id);
        portIds.add(edge.from.port_id).add(edge.to.port_id);
    });

    return { connectionIds, portIds };
}

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

/** The end revealed closer to the focal object; the picked card on a tie. */
function traceStart(graph: CablingGraph, edge: CablingEdge, pickedObjectId: number | null): number | null {
    const [near, far] = edge.from.object_id === pickedObjectId ? [edge.from, edge.to] : [edge.to, edge.from];

    return generation(graph, far.object_id) < generation(graph, near.object_id) ? far.object_id : near.object_id;
}


function generation(graph: CablingGraph, objectId: number | null): number {
    return (objectId == null ? undefined : graph.reveals.get(objectId)?.generation) ?? Infinity;
}


/** The cables between each card and the one it was revealed from, from this card back to the focal object. */
function revealChain(graph: CablingGraph, objectId: number | null): CablingEdge[] {
    const chain: CablingEdge[] = [];
    let cardId = objectId;
    let reveal = cardId == null ? undefined : graph.reveals.get(cardId);

    // Reveals form a tree; the hop bound only stops a malformed one from looping.
    for (let hops = 0; cardId != null && reveal?.parentId != null && hops < graph.reveals.size; hops++) {
        const parentId = reveal.parentId;
        const cables = hopCables(graph, cardId, parentId, reveal);

        if (!cables.length) {
            break;
        }

        chain.push(...cables);
        cardId = parentId;
        reveal = graph.reveals.get(parentId);
    }

    return chain;
}


/** The cable a card was revealed by, plus every other drawn cable between the same two cards. */
function hopCables(graph: CablingGraph, cardId: number, parentId: number, reveal: CablingReveal): CablingEdge[] {
    const cable = revealCable(graph, reveal);

    if (!cable) {
        return [];
    }

    // Each port of a panel on the way leads to its own pair, so only the reveal cable is on the trace.
    const viaPanel = isPatchPanelNode(graph.nodes.get(cardId))
        || (parentId !== graph.focalId && isPatchPanelNode(graph.nodes.get(parentId)));

    return viaPanel ? [cable] : [...graph.edges.values()].filter((edge) => joins(edge, cardId, parentId));
}


/** Port ids are unique, so the reveal's two ports identify its cable. */
function revealCable(graph: CablingGraph, reveal: CablingReveal): CablingEdge | undefined {
    return [...graph.edges.values()].find((edge) => hasPort(edge, reveal.parentPortId) && hasPort(edge, reveal.ownPortId));
}


function hasPort(edge: CablingEdge, portId: number | null): boolean {
    return portId != null && (edge.from.port_id === portId || edge.to.port_id === portId);
}


function joins(edge: CablingEdge, firstId: number, secondId: number): boolean {
    const ends = [edge.from.object_id, edge.to.object_id];

    return ends.includes(firstId) && ends.includes(secondId);
}
