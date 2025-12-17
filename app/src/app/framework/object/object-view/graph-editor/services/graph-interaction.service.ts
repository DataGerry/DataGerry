/*
* DATAGERRY - OpenSource Enterprise CMDB
* Copyright (C) 2025 becon GmbH
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
export class GraphInteractionService {

  /**
   * Shows the create menu for adding new objects or connections
   */
  showCreateMenu(
    parentNodeForCreate: GraphNode | null,
    createMenuX: number,
    createMenuY: number,
    createMenuVisible: boolean,
    contextMenuVisible: boolean
  ): {
    parentNodeForCreate: GraphNode | null;
    createMenuX: number;
    createMenuY: number;
    createMenuVisible: boolean;
    contextMenuVisible: boolean;
  } {
    return {
      parentNodeForCreate: parentNodeForCreate,
      createMenuX: createMenuX,
      createMenuY: createMenuY,
      createMenuVisible: true,
      contextMenuVisible: false
    };
  }

  /**
   * Handles right-click events on a node to show the context menu
   */
  onRightClick(
    event: MouseEvent,
    node: GraphNode,
    selectedNode: GraphNode | null,
    selectedNodes: Set<number>,
    contextMenuX: number,
    contextMenuY: number,
    contextMenuVisible: boolean,
    createMenuVisible: boolean
  ): {
    selectedNode: GraphNode | null;
    selectedNodes: Set<number>;
    contextMenuX: number;
    contextMenuY: number;
    contextMenuVisible: boolean;
    createMenuVisible: boolean;
  } {
    if (node.isRoot) {
      return {
        selectedNode: selectedNode,
        selectedNodes: selectedNodes,
        contextMenuX: contextMenuX,
        contextMenuY: contextMenuY,
        contextMenuVisible: false,
        createMenuVisible: createMenuVisible
      };
    }

    event.preventDefault();
    event.stopPropagation();

    // Don't call selectNode here, just set the selection directly
    const newSelectedNodes = new Set<number>();
    newSelectedNodes.add(node.id);

    return {
      selectedNode: node,
      selectedNodes: newSelectedNodes,
      contextMenuX: event.clientX,
      contextMenuY: event.clientY,
      contextMenuVisible: true,
      createMenuVisible: false
    };
  }

  /**
   * Handles mouse down events on the canvas for panning
   */
  onCanvasMouseDown(
    event: MouseEvent,
    isPanning: boolean,
    panStartX: number,
    panStartY: number,
    viewportX: number,
    viewportY: number,
    clearSelection: () => void
  ): {
    isPanning: boolean;
    panStartX: number;
    panStartY: number;
  } {
    if (event.button !== 0) {
      return { isPanning, panStartX, panStartY };
    }

    if (!event.shiftKey && !event.ctrlKey) {
      clearSelection();
    }

    return {
      isPanning: true,
      panStartX: event.clientX - viewportX,
      panStartY: event.clientY - viewportY
    };
  }

  /**
   * Handles mouse down events on a node
   */
  onNodeMouseDown(
    event: MouseEvent,
    node: GraphNode,
    isDragging: boolean,
    isMultiSelecting: boolean,
    selectedNodes: Set<number>,
    dragOffsetX: number,
    dragOffsetY: number,
    toggleNodeSelection: (node: GraphNode) => void,
    selectNode: (node: GraphNode, event?: MouseEvent) => void
  ): {
    isDragging: boolean;
    isMultiSelecting: boolean;
    selectedNodes: Set<number>;
    dragOffsetX: number;
    dragOffsetY: number;
  } {
    if (event.button !== 0 || node.isLoading) {
      return { isDragging, isMultiSelecting, selectedNodes, dragOffsetX, dragOffsetY };
    }

    // Check if the click is on an action button
    const target = event.target as HTMLElement;
    if (target.closest('.action-btn')) {
      event.stopPropagation();
      return { isDragging, isMultiSelecting, selectedNodes, dragOffsetX, dragOffsetY };
    }

    event.stopPropagation();

    let newIsDragging = true;
    let newIsMultiSelecting = false;
    const newSelectedNodes = new Set<number>(selectedNodes);

    if (event.shiftKey || event.ctrlKey) {
      newIsMultiSelecting = true;
      toggleNodeSelection(node);
    } else if (!selectedNodes.has(node.id)) {
      // Pass the event to selectNode to check for conflicts
      selectNode(node, event);
    }

    return {
      isDragging: newIsDragging,
      isMultiSelecting: newIsMultiSelecting,
      selectedNodes: newSelectedNodes,
      dragOffsetX: event.clientX - node.x,
      dragOffsetY: event.clientY - node.y
    };
  }
}
