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
import { Injectable } from '@angular/core';
import { GraphNode, Connection } from '../interfaces/graph.interfaces';
import { LAYOUT_CONFIG } from '../constants/graph.constants';

@Injectable()
export class GraphPathService {

    calculatePath(conn: Connection, nodeInstanceMap: Map<string, GraphNode>): string {
        let from = conn?.fromUid ? nodeInstanceMap?.get(conn?.fromUid)
            : this.getNodeByIdAndLevel(nodeInstanceMap, conn?.from, conn?.fromLevel);
        let to = conn?.toUid ? nodeInstanceMap?.get(conn?.toUid)
            : this.getNodeByIdAndLevel(nodeInstanceMap, conn?.to, conn?.toLevel);

        if (!from || !to) { return ''; }

        const { nodeWidth, nodeHeight } = LAYOUT_CONFIG;

        // Determine if the path should be reversed (for parent side, levels < 0)
        const reverse = from?.level < 0;
        let startNode, endNode;

        if (reverse) {
            startNode = to;
            endNode = from;
        } else {
            startNode = from;
            endNode = to;
        }

        // Calculate start and end coordinates
        const startX = startNode?.x + nodeWidth / 2;
        const endX = endNode?.x + nodeWidth / 2;
        let startY, endY;

        if (startNode?.y < endNode?.y) {
            startY = startNode?.y + nodeHeight; // Bottom of start node
            endY = endNode?.y;                  // Top of end node
        } else {
            startY = startNode?.y;              // Top of start node
            endY = endNode?.y + nodeHeight;     // Bottom of end node
        }

        // Generate the path
        const midY = (startY + endY) / 2;
        if (Math.abs(startX - endX) < 50) {
            return `M ${startX} ${startY} L ${endX} ${endY}`;
        }
        return `M ${startX} ${startY} C ${startX} ${midY}, ${endX} ${midY}, ${endX} ${endY}`;
    }



    calculateLabelPosition(conn: Connection, nodes: GraphNode[]): { x: number; y: number } {
        const fromNode = nodes?.find(n => n?.id === conn?.from && n?.level === conn?.fromLevel);
        const toNode = nodes?.find(n => n?.id === conn?.to && n?.level === conn?.toLevel);

        if (!fromNode || !toNode) return { x: 0, y: 0 };

        const { nodeWidth, nodeHeight } = LAYOUT_CONFIG;
        const fromX = fromNode?.x + nodeWidth / 2;
        const fromY = fromNode?.y + nodeHeight;
        const toX = toNode?.x + nodeWidth / 2;
        const toY = toNode?.y;

        return {
            x: (fromX + toX) / 2,
            y: (fromY + toY) / 2,
        };
    }

    getArrowMarker(conn: Connection, showDataFlow: boolean): string {
        let isUpward = false;

        if (conn?.fromLevel === 0 && conn?.toLevel === 1) {
            isUpward = true;
        } else if (conn?.fromLevel === 1 && conn?.toLevel === 0) {
            isUpward = true;
        } else if (conn?.fromLevel === -1 && conn?.toLevel === 0) {
            isUpward = false;
        } else if (conn?.fromLevel === 0 && conn?.toLevel === -1) {
            isUpward = false;
        }


        if (conn?.dataFlow && showDataFlow) {
            return isUpward ? 'url(#arrow-data-flow-up)' : 'url(#arrow-data-flow)';
        } else if (conn?.isValid) {
            return isUpward ? 'url(#arrow-valid-up)' : 'url(#arrow-valid)';
        } else {
            return isUpward ? 'url(#arrow-invalid-up)' : 'url(#arrow-invalid)';
        }
    }


    getConnectionStrokeWidth(conn: Connection): number {
        const baseWidth = 3;
        const strengthMultiplier = conn?.strength || 1;
        return baseWidth * Math.min(strengthMultiplier, 3);
    }

    private getNodeByIdAndLevel(nodeInstanceMap: Map<string, GraphNode>, id: number, level: number): GraphNode | undefined {
        for (const node of nodeInstanceMap?.values()) {
            if (node?.id === id && node?.level === level) {
                return node;
            }
        }
        return undefined;
    }

    validateConnections(connections: Connection[], nodeInstanceMap: Map<string, GraphNode>): Connection[] {

        const ok: Connection[] = [];
        const seen = new Set<string>();

        connections?.forEach(c => {
            const from = nodeInstanceMap?.get(c?.fromUid ?? '');
            const to = nodeInstanceMap?.get(c?.toUid ?? '');

            if (!from || !to) {
                return;
            }

            const diff = Math.abs(from?.level - to?.level);
            if (diff !== 1) {
                return;
            }

            const key = `${from?.uid}|${to?.uid}`;
            if (seen?.has(key)) { return; }
            seen.add(key);

            c.fromLevel = from?.level;
            c.toLevel = to?.level;
            c.isValid = true;
            ok.push(c);
        });

        return ok;
    }
}