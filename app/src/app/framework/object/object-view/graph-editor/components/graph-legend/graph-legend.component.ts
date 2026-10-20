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
import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

import { EDGE_STYLES, EdgeStyle } from '../../constants/graph.constants';
import { GraphEdgeKind } from '../../interfaces/graph.interfaces';

export type EdgeKindCounts = Partial<Record<GraphEdgeKind, number>>;

export interface LegendEntry {
    kind: GraphEdgeKind;
    label: string;
    style: EdgeStyle;
    count: number;
}

/** Wording follows the scope toggles in the filter panel, so the key names what produced the edge. */
const LEGEND_LABELS: ReadonlyArray<{ kind: GraphEdgeKind; label: string }> = [
    { kind: 'relation', label: 'Relations' },
    { kind: 'cable', label: 'Port connections' },
    { kind: 'ipam', label: 'IPAM relations' },
    { kind: 'location', label: 'Locations' }
];

/** Reads the edge kinds currently drawn; an unknown kind has no entry, so it is not explained. */
@Component({
    selector: 'cmdb-graph-legend',
    templateUrl: './graph-legend.component.html',
    changeDetection: ChangeDetectionStrategy.OnPush,
    host: {
        'class': 'legend',
        'role': 'region',
        'aria-label': 'Connection legend',
        '[class.is-hidden]': '!entries().length'
    },
    standalone: false
})
export class GraphLegendComponent {
    readonly counts = input<EdgeKindCounts>({});

    /** Only the kinds actually on screen, so the key never explains something that is not drawn. */
    protected readonly entries = computed<LegendEntry[]>(() => {
        const counts = this.counts();

        return LEGEND_LABELS
            .filter(entry => (counts[entry.kind] ?? 0) > 0)
            .map(entry => ({ ...entry, style: EDGE_STYLES[entry.kind], count: counts[entry.kind] ?? 0 }));
    });
}
