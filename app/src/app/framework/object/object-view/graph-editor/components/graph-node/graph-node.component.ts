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
import { ChangeDetectionStrategy, Component, computed, input, output } from '@angular/core';

import { LAYOUT_CONFIG } from '../../constants/graph.constants';
import { GraphNode } from '../../interfaces/graph.interfaces';
import { NodeTypeConfig } from '../../services/graph-editor.store';

/** One CI card on the canvas. Purely presentational; every gesture is reported upward. */
@Component({
    selector: 'cmdb-graph-node',
    templateUrl: './graph-node.component.html',
    changeDetection: ChangeDetectionStrategy.OnPush,
    host: {
        'class': 'ci-node no-select',
        '[class.selected]': 'selected()',
        '[class.expanded]': 'node().expanded',
        '[class.loading]': 'node().isLoading',
        '[class.root-node]': 'node().isRoot',
        '[class.highlighted]': 'highlighted()',
        '[style.left.px]': 'position().x',
        '[style.top.px]': 'position().y',
        '[style.width.px]': 'layout.nodeWidth',
        '[style.height.px]': 'layout.nodeHeight',
        '[style.display]': "visible() ? 'block' : 'none'"
    },
    standalone: false
})
export class GraphNodeComponent {
    readonly node = input.required<GraphNode>();
    readonly selected = input(false);
    readonly highlighted = input(false);
    readonly visible = input(true);
    readonly typeConfig = input<NodeTypeConfig | undefined>();
    readonly textColor = input('#000000');

    /** Layout eases x/y on the node object itself, so only the frame counter signals a move. */
    readonly frame = input(0);

    readonly expandToggled = output<MouseEvent>();
    readonly focusRequested = output<void>();

    readonly layout = LAYOUT_CONFIG;

    protected readonly position = computed(() => {
        this.frame();
        const node = this.node();
        return { x: node.x, y: node.y };
    });
}
