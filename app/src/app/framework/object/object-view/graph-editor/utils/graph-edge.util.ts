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

* You should have received a copy of the GNU Affero General Public License
* along with this program. If not, see <https://www.gnu.org/licenses/>.
*/
import { CIEdge, RelationMeta } from 'src/app/framework/models/ci-explorer.model';
import { safeCssColor } from 'src/app/core/utils/color-utils';
import { GraphEdgeKind } from '../interfaces/graph.interfaces';

/** The edge one neighbour is reached by, kept together so one walk answers kind and cable alike. */
export interface NeighbourEdge {
    kind: GraphEdgeKind;
    meta?: RelationMeta;
}

/** An edge carries a list of relations; everything drawn from it uses the first. */
export function edgeMeta(edge: CIEdge): RelationMeta | undefined {
    return Array.isArray(edge?.metadata) ? edge.metadata[0] : edge?.metadata;
}

export function isUndirectedEdge(edge: CIEdge): boolean {
    return edgeMeta(edge)?.undirected === true;
}

/**
 * The far endpoints of the undirected edges touching `nodeId`.
 *
 * Expansion builds its own connections instead of reusing the backend edges, so this is
 * how an expanded port connection keeps the flag that suppresses its arrow head.
 */
export function undirectedNeighbours(edges: CIEdge[], nodeId: number): Set<number> {
    const neighbours = new Set<number>();

    edges.forEach(edge => {
        if (!isUndirectedEdge(edge)) {
            return;
        }

        if (edge.from === nodeId) {
            neighbours.add(edge.to);
        }

        if (edge.to === nodeId) {
            neighbours.add(edge.from);
        }
    });

    return neighbours;
}

/** A location edge arrives bare, so absent metadata is itself the marker. */
export function edgeKind(meta: RelationMeta | undefined): GraphEdgeKind {
    if (!meta) {
        return 'location';
    }

    switch (meta.source) {
        case 'port_connection': return 'cable';
        case 'ipam': return 'ipam';
        case undefined: return meta.relation_id != null ? 'relation' : 'unknown';
        default: return 'unknown';
    }
}

/** A collapsed path can span several hops, so the first coloured cable names the run. */
export function cableColorOf(meta: RelationMeta | undefined): string | null {
    for (const hop of meta?.path ?? []) {
        const color = safeCssColor(hop.cable?.color);

        if (color) {
            return color;
        }
    }

    return null;
}

/**
 * The edge reaching each far endpoint of `nodeId`.
 *
 * Expansion builds its own connections instead of reusing the backend edges, so this is how an
 * expanded edge keeps what it was - a missing entry means no edge was returned, not a bare one.
 */
export function edgeByNeighbour(edges: CIEdge[], nodeId: number): Map<number, NeighbourEdge> {
    const byNeighbour = new Map<number, NeighbourEdge>();

    /** A pair can be both related and cabled; the cable wins, as it already does for the arrow head. */
    const claim = (neighbourId: number, neighbour: NeighbourEdge) => {
        if (byNeighbour.get(neighbourId)?.kind === 'cable') {
            return;
        }

        byNeighbour.set(neighbourId, neighbour);
    };

    edges.forEach(edge => {
        const meta = edgeMeta(edge);
        const neighbour: NeighbourEdge = { kind: edgeKind(meta), meta };

        if (edge.from === nodeId) {
            claim(edge.to, neighbour);
        }

        if (edge.to === nodeId) {
            claim(edge.from, neighbour);
        }
    });

    return byNeighbour;
}
