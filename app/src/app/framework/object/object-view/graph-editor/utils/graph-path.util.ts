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
import { LAYOUT_CONFIG } from '../constants/graph.constants';
import { Connection, GraphNode } from '../interfaces/graph.interfaces';

/** Below this horizontal gap a curve reads as a wobble, so the edge is drawn straight. */
const STRAIGHT_LINE_THRESHOLD = 50;

const BASE_STROKE_WIDTH = 3;
const MAX_STRENGTH_MULTIPLIER = 3;

function findByIdAndLevel(
    nodeInstanceMap: Map<string, GraphNode>,
    id: number,
    level: number
): GraphNode | undefined {
    for (const node of nodeInstanceMap.values()) {
        if (node.id === id && node.level === level) {
            return node;
        }
    }
    return undefined;
}

/**
 * Builds the SVG `d` attribute for one edge. Parent edges are drawn from the lower node
 * upward, so the curve always leaves the box that sits higher on the canvas.
 */
export function calculatePath(conn: Connection, nodeInstanceMap: Map<string, GraphNode>): string {
    const from = conn.fromUid
        ? nodeInstanceMap.get(conn.fromUid)
        : findByIdAndLevel(nodeInstanceMap, conn.from, conn.fromLevel);
    const to = conn.toUid
        ? nodeInstanceMap.get(conn.toUid)
        : findByIdAndLevel(nodeInstanceMap, conn.to, conn.toLevel);

    if (!from || !to) {
        return '';
    }

    const { nodeWidth, nodeHeight } = LAYOUT_CONFIG;
    const reverse = from.level < 0;
    const startNode = reverse ? to : from;
    const endNode = reverse ? from : to;

    const startX = startNode.x + nodeWidth / 2;
    const endX = endNode.x + nodeWidth / 2;

    const goingDown = startNode.y < endNode.y;
    const startY = goingDown ? startNode.y + nodeHeight : startNode.y;
    const endY = goingDown ? endNode.y : endNode.y + nodeHeight;

    if (Math.abs(startX - endX) < STRAIGHT_LINE_THRESHOLD) {
        return `M ${startX} ${startY} L ${endX} ${endY}`;
    }

    const midY = (startY + endY) / 2;
    return `M ${startX} ${startY} C ${startX} ${midY}, ${endX} ${midY}, ${endX} ${endY}`;
}

/** Sits midway between the source's bottom edge and the target's top edge. */
export function calculateLabelPosition(conn: Connection, nodes: GraphNode[]): { x: number; y: number } {
    const fromNode = nodes.find(n => n.id === conn.from && n.level === conn.fromLevel);
    const toNode = nodes.find(n => n.id === conn.to && n.level === conn.toLevel);

    if (!fromNode || !toNode) {
        return { x: 0, y: 0 };
    }

    const { nodeWidth, nodeHeight } = LAYOUT_CONFIG;

    return {
        x: ((fromNode.x + nodeWidth / 2) + (toNode.x + nodeWidth / 2)) / 2,
        y: ((fromNode.y + nodeHeight) + toNode.y) / 2
    };
}

export function getConnectionStrokeWidth(conn: Connection): number {
    return BASE_STROKE_WIDTH * Math.min(conn.strength || 1, MAX_STRENGTH_MULTIPLIER);
}

/**
 * Drops edges whose endpoints are no longer rendered or no longer adjacent, keeping one
 * edge per ordered instance pair. Levels are restamped from the live nodes.
 */
export function validateConnections(
    connections: Connection[],
    nodeInstanceMap: Map<string, GraphNode>
): Connection[] {
    const kept: Connection[] = [];
    const seen = new Set<string>();

    connections.forEach(conn => {
        const from = nodeInstanceMap.get(conn.fromUid ?? '');
        const to = nodeInstanceMap.get(conn.toUid ?? '');

        if (!from || !to || Math.abs(from.level - to.level) !== 1) {
            return;
        }

        const key = `${from.uid}|${to.uid}`;
        if (seen.has(key)) {
            return;
        }
        seen.add(key);

        conn.fromLevel = from.level;
        conn.toLevel = to.level;
        conn.isValid = true;
        kept.push(conn);
    });

    return kept;
}
