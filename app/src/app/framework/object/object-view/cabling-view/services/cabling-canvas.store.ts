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
import { Injectable, computed, signal } from '@angular/core';

import { CABLING_ZOOM } from '../constants/cabling.constants';
import { CablingSize, CablingViewport } from '../models/cabling-viewport.types';
import { CablingBounds, CablingPoint } from '../models/cabling.types';
import {
    centerViewport,
    containsBounds,
    fitViewport,
    visibleCanvas,
    zoomAround
} from '../utils/cabling-viewport.util';
/* ------------------------------------------------------------------------------------------------------------------ */

/** Where one cabling canvas looks and where its cards were dragged to. Provided per view. */
@Injectable()
export class CablingCanvasStore {

    private readonly viewportState = signal<CablingViewport>({ x: 0, y: 0, zoom: 1 });
    private readonly offsetsState = signal<ReadonlyMap<number, CablingPoint>>(new Map());
    private readonly panningState = signal(false);
    private readonly animateState = signal(false);
    private frame: HTMLElement | null = null;

    public readonly viewport = this.viewportState.asReadonly();
    public readonly offsets = this.offsetsState.asReadonly();
    public readonly isPanning = this.panningState.asReadonly();

    /** Off while a gesture drives the canvas, so it follows the pointer without lag. */
    public readonly animate = this.animateState.asReadonly();

    public readonly transform = computed(() => {
        const { x, y, zoom } = this.viewport();

        return `translate(${ x }px, ${ y }px) scale(${ zoom })`;
    });

    public readonly canZoomIn = computed(() => this.viewport().zoom < CABLING_ZOOM.max);
    public readonly canZoomOut = computed(() => this.viewport().zoom > CABLING_ZOOM.min);

    /** Set when a press ended as a pan or a drag, so the click that follows it selects nothing. */
    public dragged = false;

/* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    /** The frame the canvas is clipped by; the gestures directive on it attaches it. */
    public attach(frame: HTMLElement): void {
        this.frame = frame;
    }


    public frameRect(): DOMRect {
        return this.frame?.getBoundingClientRect() ?? new DOMRect();
    }


    public zoomIn(): void {
        this.zoomBy(CABLING_ZOOM.step);
    }


    public zoomOut(): void {
        this.zoomBy(1 / CABLING_ZOOM.step);
    }


    /** Keeps the canvas point under `screenPoint` in place; not eased, so it keeps up with the wheel. */
    public zoomAt(factor: number, screenPoint: CablingPoint): void {
        this.move(zoomAround(this.viewport(), this.viewport().zoom * factor, screenPoint), false);
    }


    public panBy(dx: number, dy: number): void {
        const { x, y, zoom } = this.viewport();

        this.move({ x: x + dx, y: y + dy, zoom }, true);
    }


    /** Follows a pan gesture; the gesture has already turned easing off. */
    public panTo(x: number, y: number): void {
        this.viewportState.update((viewport) => ({ ...viewport, x, y }));
    }


    public fit(bounds: CablingBounds | null, animate = true): void {
        this.move(fitViewport(bounds, this.size(), this.viewport()), animate);
    }


    /** Moves only when `target` is off screen, and then centres on `focus` around it. */
    public reveal(target: CablingBounds | null, focus: CablingBounds | null): void {
        if (!target || !focus || containsBounds(visibleCanvas(this.viewport(), this.size()), target)) {
            return;
        }

        const centre = { x: (focus.minX + focus.maxX) / 2, y: (focus.minY + focus.maxY) / 2 };

        this.move(centerViewport(centre, this.size(), this.viewport().zoom), true);
    }


    public moveCard(objectId: number, offset: CablingPoint): void {
        this.offsetsState.update((offsets) => new Map(offsets).set(objectId, offset));
    }


    public resetCards(): void {
        this.offsetsState.set(new Map());
    }


    public startGesture(): void {
        this.animateState.set(false);
        this.panningState.set(true);
    }


    public endGesture(moved: boolean): void {
        this.panningState.set(false);
        this.dragged = moved;
    }

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    private zoomBy(factor: number): void {
        const { width, height } = this.size();

        this.move(zoomAround(this.viewport(), this.viewport().zoom * factor, { x: width / 2, y: height / 2 }), true);
    }


    private move(viewport: CablingViewport, animate: boolean): void {
        this.animateState.set(animate);
        this.viewportState.set(viewport);
    }


    private size(): CablingSize {
        const { width, height } = this.frameRect();

        return { width, height };
    }
}
