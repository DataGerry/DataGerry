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
import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';

import { LAYOUT_CONFIG } from '../../constants/graph.constants';
import { GraphNode, NodeGroup } from '../../interfaces/graph.interfaces';

/** Scaled-down overview of the whole graph; clicking it recentres the viewport. */
@Component({
    selector: 'cmdb-graph-minimap',
    templateUrl: './graph-minimap.component.html',
    changeDetection: ChangeDetectionStrategy.OnPush,
    host: {
        'class': 'minimap',
        '(click)': 'minimapClick.emit($event)'
    },
    standalone: false
})
export class GraphMinimapComponent {
    readonly nodes = input<GraphNode[]>([]);
    readonly groups = input<NodeGroup[]>([]);
    readonly selectedNodes = input<Set<number>>(new Set<number>());
    readonly viewBox = input('');
    readonly viewportRect = input<{ x: number; y: number; width: number; height: number } | null>(null);

    readonly minimapClick = output<MouseEvent>();

    readonly layout = LAYOUT_CONFIG;

    /** Root green, children blue, parents amber - the same key the canvas uses. */
    bandColor(level: number): string {
        return level === 0 ? '#4CAF50' : level > 0 ? '#2196F3' : '#FF9800';
    }

    nodeColor(node: GraphNode): string {
        return node.isRoot ? '#4CAF50' : node.level > 0 ? '#2196F3' : '#FF9800';
    }
}
