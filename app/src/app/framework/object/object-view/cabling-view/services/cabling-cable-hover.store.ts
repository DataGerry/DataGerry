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
import { Injectable, inject, signal } from '@angular/core';

import { CablingCableHover, CablingPathProbe, CablingPathSample } from '../models/cabling-tooltip.types';
import { nearestPointOnPath, samplePath } from '../utils/cabling-path.util';
import { placeCableTooltip } from '../utils/cabling-tooltip.util';
import { canvasToScreen, screenToCanvas } from '../utils/cabling-viewport.util';
import { CablingCanvasStore } from './cabling-canvas.store';
/* ------------------------------------------------------------------------------------------------------------------ */

/** Where on the hovered cable its tooltip points. Provided per view, beside the canvas it measures. */
@Injectable()
export class CablingCableHoverStore {

    private readonly canvas = inject(CablingCanvasStore);
    private readonly hoverState = signal<CablingCableHover | null>(null);
    private probe: CablingPathProbe | null = null;

    public readonly hover = this.hoverState.asReadonly();

/* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    /** Snaps to the spot on the cable nearest the pointer; a touch points at nothing. */
    public track(event: PointerEvent, connectionId: number): void {
        const path = event.currentTarget;

        if (event.pointerType === 'touch' || !(path instanceof SVGGeometryElement)) {
            return;
        }

        const frame = this.canvas.frameRect();
        const viewport = this.canvas.viewport();
        const pointer = screenToCanvas({ x: event.clientX - frame.left, y: event.clientY - frame.top }, viewport);
        const spot = canvasToScreen(nearestPointOnPath(path, this.samples(path), pointer), viewport);

        this.hoverState.set({ connectionId, viewport, placement: placeCableTooltip(spot, frame) });
    }


    public clear(): void {
        this.probe = null;
        this.hoverState.set(null);
    }

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    /** Sampled once per path and shape, so following the pointer stays cheap. */
    private samples(path: SVGGeometryElement): CablingPathSample[] {
        const d = path.getAttribute('d');

        if (this.probe?.path !== path || this.probe.d !== d) {
            this.probe = { path, d, samples: samplePath(path) };
        }

        return this.probe.samples;
    }
}
