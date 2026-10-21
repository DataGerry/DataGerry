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
import { Connection, GraphNode, NodeGroup } from '../interfaces/graph.interfaces';
import { GraphLayoutInput, GraphLayoutResult, LayoutAxes, Point } from '../models/graph-layout.types';

const SNAP_GRID = 20;

/** Spacing and half-box size along each axis, for whichever role that axis plays. */
function metrics(axes: LayoutAxes) {
    const { horizontalSpacing, verticalSpacing, nodeWidth, nodeHeight, centerX, centerY } = LAYOUT_CONFIG;

    return {
        siblingSpacing: axes.siblingAxis === 'x' ? horizontalSpacing : verticalSpacing,
        levelSpacing: axes.levelAxis === 'y' ? verticalSpacing : horizontalSpacing,
        siblingCenter: axes.siblingAxis === 'x' ? centerX : centerY,
        levelCenter: axes.levelAxis === 'y' ? centerY : centerX,
        siblingHalfBox: axes.siblingAxis === 'x' ? nodeWidth / 2 : nodeHeight / 2,
        levelHalfBox: axes.levelAxis === 'y' ? nodeHeight / 2 : nodeWidth / 2
    };
}

function mean(values: number[]): number {
    return values.reduce((sum, v) => sum + v, 0) / values.length;
}

/**
 * Lays a graph out in bands, one per level, and spreads each band's nodes around the
 * average position of the neighbours they hang from.
 *
 * Positions are built up in a working map rather than written onto the nodes, because a
 * band is anchored against the bands already placed - the root first, then children
 * outward, then parents outward.
 */
export function computeHierarchicalLayout(input: GraphLayoutInput, axes: LayoutAxes): GraphLayoutResult {
    const { nodes, connections, nodeInstanceMap } = input;
    const { siblingSpacing, levelSpacing, siblingCenter, levelCenter, siblingHalfBox, levelHalfBox } = metrics(axes);

    const placements = new Map<string, Point>(nodes.map(n => [n.uid, { x: n.x, y: n.y }]));
    const groups: NodeGroup[] = [];

    const positionOf = (uid: string | undefined): Point | undefined => {
        if (!uid) {
            return undefined;
        }
        const placed = placements.get(uid);
        if (placed) {
            return placed;
        }
        const known = nodeInstanceMap.get(uid);
        return known ? { x: known.x, y: known.y } : undefined;
    };

    const siblingOf = (uid: string): number => positionOf(uid)![axes.siblingAxis];

    const write = (node: GraphNode, alongSibling: number, alongLevel: number): void => {
        const point = placements.get(node.uid) ?? { x: node.x, y: node.y };
        point[axes.siblingAxis] = alongSibling;
        point[axes.levelAxis] = alongLevel;
        placements.set(node.uid, point);
    };

    const byLevel = new Map<number, GraphNode[]>();
    nodes.forEach(node => {
        if (!byLevel.has(node.level)) {
            byLevel.set(node.level, []);
        }
        byLevel.get(node.level)!.push(node);
    });
    const orderedLevels = Array.from(byLevel.keys()).sort((a, b) => a - b);

    /** Mean position of the neighbours one level closer to the root. */
    const anchorOf = (node: GraphNode, neighbourLevel: number): number => {
        const neighbours = connections
            .filter(c => !!c.isValid && (
                (c.toUid === node.uid && c.fromLevel === neighbourLevel) ||
                (c.fromUid === node.uid && c.toLevel === neighbourLevel)
            ))
            .map(c => positionOf(c.toUid === node.uid ? c.fromUid : c.toUid))
            .filter((p): p is Point => !!p);

        return neighbours.length
            ? mean(neighbours.map(p => p[axes.siblingAxis]))
            : siblingOf(node.uid);
    };

    const placeBand = (level: number, anchoredAgainst: number | null): void => {
        const band = byLevel.get(level);
        if (!band?.length) {
            return;
        }

        const alongLevel = level === 0 ? levelCenter : levelCenter + level * levelSpacing;
        const spread = (band.length - 1) * siblingSpacing;

        let ordered = band;
        let start: number;

        if (anchoredAgainst === null) {
            start = siblingCenter - spread / 2;
        } else {
            const anchored = band
                .map(node => ({ node, anchor: anchorOf(node, anchoredAgainst) }))
                .sort((a, b) => a.anchor - b.anchor);
            ordered = anchored.map(a => a.node);
            start = mean(anchored.map(a => a.anchor)) - spread / 2;
        }

        ordered.forEach((node, index) => write(node, start + index * siblingSpacing, alongLevel));

        const bandStart = Math.min(...band.map(node => siblingOf(node.uid)));
        const group: NodeGroup = { level, nodes: band, x: 0, y: 0, collapsed: false };
        group[axes.siblingAxis] = bandStart - siblingHalfBox;
        group[axes.levelAxis] = alongLevel - levelHalfBox;
        groups.push(group);
    };

    if (byLevel.has(0)) {
        placeBand(0, null);
    }
    orderedLevels.filter(l => l > 0).forEach(level => placeBand(level, level - 1));
    orderedLevels.filter(l => l < 0).reverse().forEach(level => placeBand(level, level + 1));

    if (input.magneticSnap !== false) {
        applyMagneticSnap(nodes, placements);
    }

    return { placements, groups };
}

/**
 * Pulls positions onto the grid and onto nearby neighbours. The threshold is wider than
 * the grid, so every node lands on a grid multiple.
 *
 * Nodes are compared by CI id, so the two instances of a CI that is both a parent and a
 * child never snap onto each other.
 */
function applyMagneticSnap(nodes: GraphNode[], placements: Map<string, Point>): void {
    const { magneticSnapThreshold } = LAYOUT_CONFIG;

    nodes.forEach(node => {
        const point = placements.get(node.uid)!;
        const snappedX = Math.round(point.x / SNAP_GRID) * SNAP_GRID;
        const snappedY = Math.round(point.y / SNAP_GRID) * SNAP_GRID;

        if (Math.abs(point.x - snappedX) < magneticSnapThreshold) {
            point.x = snappedX;
        }
        if (Math.abs(point.y - snappedY) < magneticSnapThreshold) {
            point.y = snappedY;
        }

        nodes.forEach(other => {
            if (node.id === other.id) {
                return;
            }
            const otherPoint = placements.get(other.uid)!;
            if (Math.abs(point.x - otherPoint.x) < magneticSnapThreshold) {
                point.x = otherPoint.x;
            }
            if (Math.abs(point.y - otherPoint.y) < magneticSnapThreshold) {
                point.y = otherPoint.y;
            }
        });
    });
}

/** Connections carry uids, so an edge can be followed without scanning the node list. */
export function buildAdjacencyIndex(connections: Connection[]): Map<string, Connection[]> {
    const index = new Map<string, Connection[]>();

    const add = (uid: string | undefined, conn: Connection): void => {
        if (!uid) {
            return;
        }
        const bucket = index.get(uid);
        bucket ? bucket.push(conn) : index.set(uid, [conn]);
    };

    connections.forEach(conn => {
        if (!conn.isValid) {
            return;
        }
        add(conn.fromUid, conn);
        add(conn.toUid, conn);
    });

    return index;
}
