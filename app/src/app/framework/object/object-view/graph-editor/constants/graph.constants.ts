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

import { GraphEdgeKind } from '../interfaces/graph.interfaces';

export interface EdgeStyle {
    stroke: string;
    dash: string | null;
    /** Left out so the edge keeps the strength-based width. */
    width?: number;
}

/**
 * What each edge source looks like, shared by the canvas and the legend. Colour is never the only
 * channel - the dash pattern and the arrow head carry the same distinction without hue.
 *
 * Every stroke clears 3:1 against the #f0f2f5 canvas, which WCAG 1.4.11 asks of a graphical object.
 */
export const EDGE_STYLES: Readonly<Record<GraphEdgeKind, EdgeStyle>> = {
    relation: { stroke: '#607D8B', dash: null, width: 3 },
    cable: { stroke: '#8E44AD', dash: null, width: 3 },
    ipam: { stroke: '#3B7DD8', dash: '6 4', width: 3 },
    location: { stroke: '#546E7A', dash: '2 4', width: 3 },
    unknown: { stroke: '#607D8B', dash: null }
};

export const LAYOUT_CONFIG = {
    nodeWidth: 220,
    nodeHeight: 110,
    horizontalSpacing: 320,
    verticalSpacing: 250,
    centerX: 800,
    centerY: 450,
    animationDuration: 50,
    magneticSnapThreshold: 30,
  };
  
  export const KEYBOARD_SHORTCUTS = {
    'Delete': 'deleteSelectedNodes',
    'Escape': 'clearSelection',
    'Enter': 'focusOnSelected',
    'Space': 'toggleExpandSelected',
    'ArrowUp': 'navigateUp',
    'ArrowDown': 'navigateDown',
    'ArrowLeft': 'navigateLeft',
    'ArrowRight': 'navigateRight',
    'Ctrl+A': 'selectAllNodes',
    'Ctrl+F': 'focusSearch',
    'Ctrl+R': 'setSelectedAsRoot',
    'Ctrl+Plus': 'zoomIn',
    'Ctrl+Minus': 'zoomOut',
    'Ctrl+0': 'resetZoom',
  } as const;