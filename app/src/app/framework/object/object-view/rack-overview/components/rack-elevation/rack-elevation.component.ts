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
import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';

import { RackDropBand } from '../../models/rack-dnd.types';
import { RackArea, RackViewMode, RackViewSide } from '../../models/rack-overview.types';
import { RackActionsService } from '../../services/rack-actions.service';
import { RackDragService } from '../../services/rack-drag.service';
import { RackOverviewStore } from '../../services/rack-overview-store.service';
/* ------------------------------------------------------------------------------------------------------------------ */


/**
 * The drawing itself: the two side rails and, between them, the one grid that carries both enclosures
 * and the U ruler they share.
 *
 * Its host is the scrolling board, so everything the grid places stays inside a single component and
 * no rule has to reach across an encapsulation boundary to position a grid item.
 */
@Component({
    selector: 'cmdb-rack-elevation',
    templateUrl: './rack-elevation.component.html',
    styleUrls: ['./rack-elevation.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    host: { class: 'rack-board' },
    standalone: false
})
export class RackElevationComponent {

    public readonly store = inject(RackOverviewStore);
    public readonly drag = inject(RackDragService);
    public readonly actions = inject(RackActionsService);

    public readonly viewMode = input.required<RackViewMode>();

    /** Where the tooltips of this drawing are parked, which fullscreen changes. */
    public readonly tooltipContainer = input<string | null>('body');

    public readonly AREAS = RackArea;

    public readonly shownFace = computed(() =>
        this.viewMode() === 'rear' ? this.store.rearFace() : this.store.frontFace());

    /** The face a single-face view is showing, and the face a full depth preview falls back to. */
    public readonly defaultSide = computed<RackViewSide>(() =>
        this.viewMode() === 'rear' ? RackArea.BACK : RackArea.FRONT);

    /**
     * The preview of where a drag would land, once per face it claims. A face this view does not draw
     * is left out, so a full depth row previews on one cabinet in a single-face view.
     */
    public readonly dropBands = computed<RackDropBand[]>(() => {
        const plan = this.drag.dropPlan();

        if (!plan?.gridRow) {
            return [];
        }

        return plan.sides
            .filter(side => this.viewMode() === 'split' || this.defaultSide() === side)
            .map(side => ({
                side,
                isRear: side === RackArea.BACK,
                gridRow: plan.gridRow,
                label: plan.label,
                ok: plan.ok
            }));
    });
}
