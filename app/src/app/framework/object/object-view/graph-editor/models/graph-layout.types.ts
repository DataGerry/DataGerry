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
import { Connection, GraphNode, NodeGroup } from '../interfaces/graph.interfaces';

export type GraphLayoutId = 'hierarchical-top-down' | 'hierarchical-left-to-right';

/**
 * Which coordinate carries the hierarchy and which one spreads siblings.
 * Swapping the two turns a top-down layout into a left-to-right one.
 */
export interface LayoutAxes {
    /** Advances with the level index: parents at one end, children at the other. */
    readonly levelAxis: 'x' | 'y';
    /** Spreads nodes that share a level. */
    readonly siblingAxis: 'x' | 'y';
}

export interface Point {
    x: number;
    y: number;
}

export interface GraphLayoutInput {
    /** Read in array order; the result keeps that order. */
    readonly nodes: GraphNode[];
    readonly connections: Connection[];
    readonly nodeInstanceMap: Map<string, GraphNode>;
    /** Node-to-node and grid snapping, on by default. */
    readonly magneticSnap?: boolean;
}

export interface GraphLayoutResult {
    /** Where each node should end up, keyed by its rendered instance. */
    readonly placements: ReadonlyMap<string, Point>;
    readonly groups: NodeGroup[];
}

/**
 * Computes positions without touching the nodes. Applying the result, and animating
 * towards it, is the layout service's job - which is what lets a second strategy be
 * added without changing anything that renders.
 */
export interface GraphLayoutStrategy {
    readonly id: GraphLayoutId;
    apply(input: GraphLayoutInput): GraphLayoutResult;
}
