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

import { GraphNode } from '../../interfaces/graph.interfaces';

/** Right-click actions for a single node. */
@Component({
    selector: 'cmdb-graph-context-menu',
    templateUrl: './graph-context-menu.component.html',
    changeDetection: ChangeDetectionStrategy.OnPush,
    host: {
        'class': 'context-menu modern-menu',
        '[style.left.px]': 'x()',
        '[style.top.px]': 'y()'
    },
    standalone: false
})
export class GraphContextMenuComponent {
    readonly node = input.required<GraphNode>();
    readonly x = input(0);
    readonly y = input(0);
    readonly expandIcon = input('unfold_more');
    readonly expandLabel = input('Expand');

    readonly setAsRoot = output<void>();
    readonly toggleExpand = output<MouseEvent>();
    readonly focusNode = output<void>();
}
