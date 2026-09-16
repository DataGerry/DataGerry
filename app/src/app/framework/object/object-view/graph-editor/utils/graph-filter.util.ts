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
import { Connection, GraphNode } from '../interfaces/graph.interfaces';

/**
 * The graph is drawn outward from its root, so without one there is nothing to draw.
 * Duplicate instances of the same CI are kept, since each is rendered separately.
 */
export function visibleNodes(nodes: GraphNode[]): GraphNode[] {
    return nodes.some(node => node.isRoot) ? [...nodes] : [];
}

/** An edge is drawn only when both of its endpoints survived the node pass. */
export function visibleConnections(nodes: GraphNode[], connections: Connection[]): Connection[] {
    const shown = new Set(nodes.map(node => node.id));

    return connections.filter(conn => shown.has(conn.from) && shown.has(conn.to) && !!conn.isValid);
}
