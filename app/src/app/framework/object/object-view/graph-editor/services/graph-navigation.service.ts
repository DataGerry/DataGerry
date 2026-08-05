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
import { GraphNode } from '../interfaces/graph.interfaces';

@Injectable({ providedIn: 'root' })
export class GraphNavigationService {

  /**
   * Navigates through the nodes in the specified direction
   */
  navigateNodes(
    direction: 'up' | 'down' | 'left' | 'right',
    selectedNode: GraphNode | null,
    nodes: GraphNode[],
    selectNode: (node: GraphNode) => void,
    centerOnNode: (node: GraphNode) => void,
    findNodeInDirection: (from: GraphNode, dx: number, dy: number) => GraphNode | undefined
  ): void {
    if (!selectedNode) {
      if (nodes.length > 0) {
        selectNode(nodes[0]);
      }
      return;
    }

    let targetNode: GraphNode | undefined;
    switch (direction) {
      case 'up':
        targetNode = findNodeInDirection(selectedNode, 0, -1);
        break;
      case 'down':
        targetNode = findNodeInDirection(selectedNode, 0, 1);
        break;
      case 'left':
        targetNode = findNodeInDirection(selectedNode, -1, 0);
        break;
      case 'right':
        targetNode = findNodeInDirection(selectedNode, 1, 0);
        break;
    }

    if (targetNode) {
      selectNode(targetNode);
      centerOnNode(targetNode);
    }
  }
}
