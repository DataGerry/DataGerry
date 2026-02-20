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
import { Connection, GraphNode } from '../interfaces/graph.interfaces';
import { ConnectionTrackerService } from './connection-tracker.service';
import { GraphDataService } from './graph-data.service';

@Injectable()
export class GraphRootNodeService {

  constructor(
    private connectionTracker: ConnectionTrackerService,
    private graphData: GraphDataService
  ) {}

  getRootNode(nodes: GraphNode[]): GraphNode | undefined {
    return nodes.find(node => node.isRoot);
  }

  hasVisibleNodesBeyondRoot(nodes: GraphNode[]): boolean {
    return nodes.some(node => !node.isRoot);
  }

  collapseRootNode(
    rootNode: GraphNode,
    nodes: GraphNode[],
    connections: Connection[]
  ): boolean {
    const descendantUids = nodes
      .filter(node => !node.isRoot)
      .map(node => node.uid);

    if (!descendantUids.length) {
      rootNode.expanded = false;
      return false;
    }

    this.connectionTracker.removeConnectionsForCollapsedNodes(descendantUids);
    this.graphData.removeNodeInstancesByUID(nodes, connections, descendantUids);
    rootNode.expanded = false;
    return true;
  }

  getExpandIcon(node: GraphNode | null, nodes: GraphNode[]): string {
    if (!node) {
      return 'unfold_more';
    }
    if (node.isRoot) {
      return this.hasVisibleNodesBeyondRoot(nodes) ? 'unfold_less' : 'unfold_more';
    }
    return node.expanded ? 'unfold_less' : 'unfold_more';
  }

  getExpandLabel(node: GraphNode | null, nodes: GraphNode[]): string {
    if (!node) {
      return 'Expand';
    }
    if (node.isRoot) {
      return this.hasVisibleNodesBeyondRoot(nodes) ? 'Collapse' : 'Expand';
    }
    return node.expanded ? 'Collapse' : 'Expand';
  }
}
