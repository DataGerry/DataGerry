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
*
* You should have received a copy of the GNU Affero General Public License
* along with this program. If not, see <https://www.gnu.org/licenses/>.
*/
import { ChangeDetectionStrategy, Component, computed, input, output } from '@angular/core';
import { NgTemplateOutlet } from '@angular/common';
import { RouterLink } from '@angular/router';

import { CoreModule } from 'src/app/core/core.module';
import { CABLING_GEOMETRY } from '../../constants/cabling.constants';
import { CablingNodeLighting, CablingSelection, CablingSpotlight } from '../../models/cabling-spotlight.types';
import { CablingNodeLayout, CablingPortView } from '../../models/cabling.types';
import { withAlpha } from '../../utils/cabling-format.util';
/* ------------------------------------------------------------------------------------------------------------------ */

/** One object on the cabling canvas. Purely presentational; every gesture is reported upward. */
@Component({
    selector: 'cmdb-cabling-node',
    standalone: true,
    imports: [NgTemplateOutlet, RouterLink, CoreModule],
    templateUrl: './cabling-node.component.html',
    styleUrls: ['./cabling-node.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    host: {
        'class': 'cabling-node',
        'role': 'group',
        '[attr.aria-label]': 'ariaLabel()',
        '[attr.data-object-id]': 'layout().objectId',
        '[class.cabling-node--focal]': 'layout().focal',
        '[class.cabling-node--restricted]': 'layout().restricted',
        '[class.cabling-node--panel]': 'layout().patchPanel',
        '[class.cabling-node--detail]': 'detail()',
        '[class.cabling-node--lit]': 'lighting() === "lit"',
        '[class.cabling-node--shaded]': 'lighting() === "shaded"',
        '[style.left.px]': 'layout().x',
        '[style.top.px]': 'layout().y',
        '[style.width.px]': 'layout().width',
        '[style.height.px]': 'layout().height',
        '[style.--node-accent]': 'layout().accent',
        '[style.--node-accent-soft]': 'accentSoft()',
        '[style.--node-accent-line]': 'accentLine()'
    }
})
export class CablingNodeComponent {

    public readonly layout = input.required<CablingNodeLayout>();
    public readonly detail = input(false);
    public readonly highlightedConnectionId = input<number | null>(null);
    public readonly expandingPortIds = input<ReadonlySet<number>>(new Set());
    public readonly spotlight = input<CablingSpotlight | null>(null);

    public readonly expandPort = output<number>();
    public readonly toggleRows = output<void>();
    public readonly hoverConnection = output<number | null>();
    public readonly selectConnection = output<CablingSelection>();

    protected readonly geometry = CABLING_GEOMETRY;
    protected readonly openQueryParams = { view: 'cabling' };

    protected readonly accentSoft = computed(() => withAlpha(this.layout().accent, 0.12));
    protected readonly accentLine = computed(() => withAlpha(this.layout().accent, 0.45));

    protected readonly lighting = computed<CablingNodeLighting>(() => {
        const spotlight = this.spotlight();

        if (!spotlight) {
            return 'off';
        }

        return spotlight.objectId === this.layout().objectId ? 'lit' : 'shaded';
    });

    protected readonly portCountLabel = computed(() => {
        const count = this.layout().portCount;

        return `${ count } ${ count === 1 ? 'port' : 'ports' }`;
    });

    protected readonly ariaLabel = computed(() => {
        const layout = this.layout();

        return layout.restricted
            ? layout.title
            : [layout.title, layout.subtitle, this.portCountLabel(), layout.focal ? 'this object' : null]
                .filter(Boolean)
                .join(', ');
    });

    protected readonly footerLabel = computed(() => {
        const footer = this.layout().footer;

        if (!footer) {
            return '';
        }

        return footer.expanded ? 'Show fewer ports' : `${ footer.hiddenPorts } more ${ footer.hiddenPorts === 1 ? 'port' : 'ports' }`;
    });

/* ---------------------------------------------------- EVENTS ------------------------------------------------------ */

    public onPortEnter(port: CablingPortView | null): void {
        if (port?.connectionId != null) {
            this.hoverConnection.emit(port.connectionId);
        }
    }


    public onPortLeave(port: CablingPortView | null): void {
        if (port?.connectionId != null) {
            this.hoverConnection.emit(null);
        }
    }


    /** A press on the port's own buttons belongs to them, not to the cable. */
    public onPortClick(event: MouseEvent, port: CablingPortView): void {
        if (port.connectionId != null && !(event.target as Element | null)?.closest('button')) {
            const { objectId } = this.layout();

            this.selectConnection.emit({ connectionId: port.connectionId, objectId, portId: port.portId });
        }
    }

/* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    /** Under the spotlight only the picked port is marked; otherwise both ends of the highlighted cable are. */
    public isHighlighted(port: CablingPortView | null): boolean {
        const spotlight = this.spotlight();

        if (!port) {
            return false;
        }

        if (spotlight) {
            return port.portId === spotlight.portId;
        }

        return port.connectionId != null && port.connectionId === this.highlightedConnectionId();
    }


    public isExpanding(port: CablingPortView): boolean {
        return this.expandingPortIds().has(port.portId);
    }
}
