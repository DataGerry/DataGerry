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
import {
    GraphLayoutId,
    GraphLayoutInput,
    GraphLayoutResult,
    GraphLayoutStrategy,
    LayoutAxes
} from '../../models/graph-layout.types';
import { computeHierarchicalLayout } from '../../utils/graph-layout.util';

/** Parents above, children below, siblings spread left to right. */
const TOP_DOWN_AXES: LayoutAxes = { levelAxis: 'y', siblingAxis: 'x' };

export class HierarchicalTopDownStrategy implements GraphLayoutStrategy {
    readonly id: GraphLayoutId = 'hierarchical-top-down';

    apply(input: GraphLayoutInput): GraphLayoutResult {
        return computeHierarchicalLayout(input, TOP_DOWN_AXES);
    }
}
