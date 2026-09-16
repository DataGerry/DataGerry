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
