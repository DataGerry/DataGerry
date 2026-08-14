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
import { ChangeDetectionStrategy, Component, computed, inject, input, signal } from '@angular/core';
import { takeUntilDestroyed, toObservable } from '@angular/core/rxjs-interop';

import { RackArea, RackViewMode, RackViewSide } from './models/rack-overview.types';
import { RackActionsService } from './services/rack-actions.service';
import { RackDragService } from './services/rack-drag.service';
import { RackOverviewStore } from './services/rack-overview-store.service';
/* ------------------------------------------------------------------------------------------------------------------ */

/**
 * Zoom bounds for the drawing, in percent. The range leans on shrinking: a rack is taller than the
 * screen far more often than it is too small to read.
 */
const ZOOM_MIN = 80;
const ZOOM_MAX = 150;
const ZOOM_STEP = 10;
const ZOOM_DEFAULT = 100;


/**
 * The rack view. It owns how the rack is looked at - which faces, at what zoom, what is keyed in the
 * legend - and the frame those controls sit in. Everything else belongs to a part of its own:
 *
 *   {@link RackOverviewStore}  the rack, everything derived from it, and the writes that change it
 *   {@link RackDragService}    one drag gesture, from the plate grabbed to the placement written
 *   {@link RackActionsService} the actions that need a form, a confirmation or a route
 *
 * All three are provided here, so each rack view owns its own and the parts below can inject them
 * instead of being handed the same values down a chain of inputs.
 */
@Component({
    selector: 'cmdb-rack-overview',
    templateUrl: './rack-overview.component.html',
    styleUrls: ['./rack-overview.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    providers: [RackOverviewStore, RackDragService, RackActionsService],
    standalone: false
})
export class RackOverviewComponent {

    public readonly store = inject(RackOverviewStore);
    public readonly drag = inject(RackDragService);
    public readonly actions = inject(RackActionsService);

    /**
     * Nullable rather than required: the host binds the id of the object it is still loading, and a
     * required input would throw on the first pass instead of simply having nothing to draw yet.
     */
    public readonly publicId = input<number | null>(null);

    public readonly viewMode = signal<RackViewMode>('split');
    /** Scales the drawing only; the header and the side column keep their own size. */
    public readonly zoomPercent = signal(ZOOM_DEFAULT);
    public readonly isFullscreen = signal(false);
    /** The key is folded away until it is asked for; it explains the drawing, it does not replace it. */
    public readonly isLegendExpanded = signal(false);

    /** Sits on the toggle, so the key says how much it holds without having to be opened first. */
    public readonly legendCount = computed(() =>
        this.store.typesLegend().length + this.store.occupantsLegend().length);

    public readonly hasLegend = computed(() => this.legendCount() > 0);

    /** The face a new row defaults to, which is whichever one the current view leads with. */
    public readonly defaultSide = computed<RackViewSide>(() =>
        this.viewMode() === 'rear' ? RackArea.BACK : RackArea.FRONT);

    /** Also the value the board is zoomed by, so the read-out and the drawing cannot drift apart. */
    public readonly zoomLabel = computed(() => `${this.zoomPercent()}%`);

    public readonly canZoomIn = computed(() => this.zoomPercent() < ZOOM_MAX);

    public readonly canZoomOut = computed(() => this.zoomPercent() > ZOOM_MIN);

    public readonly isDefaultZoom = computed(() => this.zoomPercent() === ZOOM_DEFAULT);

    /**
     * A fullscreen element is the only thing painted, so a tooltip parked on the body would never be
     * seen. While fullscreen is open they render next to their trigger instead.
     */
    public readonly tooltipContainer = computed<string | null>(() => this.isFullscreen() ? null : 'body');

    /* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    constructor() {
        // Emits the first value as well, so this is also what loads the rack the view opens on.
        toObservable(this.publicId)
            .pipe(takeUntilDestroyed())
            .subscribe((rackId) => {
                this.viewMode.set('split');
                this.isLegendExpanded.set(false);
                this.store.open(rackId);
            });
    }

    /* ---------------------------------------------------- EVENTS ------------------------------------------------------ */

    public onViewChange(mode: RackViewMode): void {
        this.viewMode.set(mode);
    }

    public onZoomIn(): void {
        this.setZoom(this.zoomPercent() + ZOOM_STEP);
    }

    public onZoomOut(): void {
        this.setZoom(this.zoomPercent() - ZOOM_STEP);
    }

    public onResetZoom(): void {
        this.setZoom(ZOOM_DEFAULT);
    }

    /** Driven by the directive, so leaving fullscreen with Escape keeps the button in step. */
    public onFullscreenChange(isFullscreen: boolean): void {
        this.isFullscreen.set(isFullscreen);
    }

    public onToggleLegend(): void {
        this.isLegendExpanded.update(expanded => !expanded);
    }

    /* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    private setZoom(percent: number): void {
        this.zoomPercent.set(Math.min(Math.max(percent, ZOOM_MIN), ZOOM_MAX));
    }
}
