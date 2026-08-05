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