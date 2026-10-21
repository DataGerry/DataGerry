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
import { Directive, ElementRef, inject } from '@angular/core';

import { CablingGesture } from '../models/cabling-viewport.types';
import { CablingCanvasStore } from '../services/cabling-canvas.store';
import { cardObjectId } from '../utils/cabling-dom.util';
/* ------------------------------------------------------------------------------------------------------------------ */

/** A press on one of these belongs to the control, not to a pan or a drag. */
const INTERACTIVE_SELECTOR = 'a, button, input, label, select, textarea';

/** How far one notch of Ctrl + wheel zooms; pixel deltas are small, line deltas are scaled up. */
const WHEEL_ZOOM_RATE = 0.002;
const WHEEL_LINE_HEIGHT = 16;

/** Screen pixels a press may travel and still count as a click. */
const DRAG_THRESHOLD = 4;


/** Pans the canvas, drags its cards and zooms on Ctrl + wheel. Sits on the frame the canvas is clipped by. */
@Directive({
    selector: '[cmdbCablingGestures]',
    standalone: true,
    host: {
        '[class.is-panning]': 'canvas.isPanning()',
        '(pointerdown)': 'onPointerDown($event)',
        '(pointermove)': 'onPointerMove($event)',
        '(pointerup)': 'onPointerUp($event)',
        '(pointercancel)': 'onPointerUp($event)',
        '(wheel)': 'onWheel($event)'
    }
})
export class CablingGesturesDirective {

    protected readonly canvas = inject(CablingCanvasStore);
    private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);

    private gesture: CablingGesture | null = null;

/* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    constructor() {
        this.canvas.attach(this.host.nativeElement);
    }

/* ---------------------------------------------------- EVENTS ------------------------------------------------------ */

    public onPointerDown(event: PointerEvent): void {
        const target = event.target as Element | null;

        if (event.button !== 0 || this.gesture || target?.closest(INTERACTIVE_SELECTOR)) {
            return;
        }

        const objectId = cardObjectId(target);
        const { x, y } = this.canvas.viewport();

        this.canvas.dragged = false;
        this.gesture = {
            kind: objectId == null ? 'pan' : 'node',
            pointerId: event.pointerId,
            objectId,
            startX: event.clientX,
            startY: event.clientY,
            origin: objectId == null ? { x, y } : (this.canvas.offsets().get(objectId) ?? { x: 0, y: 0 }),
            moved: false
        };
    }


    public onPointerMove(event: PointerEvent): void {
        const gesture = this.gesture;

        if (!gesture || gesture.pointerId !== event.pointerId) {
            return;
        }

        const dx = event.clientX - gesture.startX;
        const dy = event.clientY - gesture.startY;

        // Captured only once it moves: a captured pointer's click lands on the canvas, not the port.
        if (!gesture.moved) {
            if (Math.hypot(dx, dy) < DRAG_THRESHOLD) {
                return;
            }

            gesture.moved = true;
            this.canvas.startGesture();

            try {
                this.host.nativeElement.setPointerCapture?.(event.pointerId);
            } catch {
                // A pointer that is no longer active cannot be captured; the gesture still follows it.
            }
        }

        if (gesture.kind === 'pan') {
            this.canvas.panTo(gesture.origin.x + dx, gesture.origin.y + dy);
            return;
        }

        // A card moves in canvas units, so the pointer's screen distance is scaled back by the zoom.
        const zoom = this.canvas.viewport().zoom;
        this.canvas.moveCard(gesture.objectId, { x: gesture.origin.x + dx / zoom, y: gesture.origin.y + dy / zoom });
    }


    public onPointerUp(event: PointerEvent): void {
        if (!this.gesture || this.gesture.pointerId !== event.pointerId) {
            return;
        }

        const element = this.host.nativeElement;

        if (element.hasPointerCapture?.(event.pointerId)) {
            element.releasePointerCapture(event.pointerId);
        }

        this.canvas.endGesture(this.gesture.moved);
        this.gesture = null;
    }


    /** Only Ctrl or Cmd + wheel zooms (a pinch reports as that too); a plain wheel keeps scrolling the page. */
    public onWheel(event: WheelEvent): void {
        if (!event.ctrlKey && !event.metaKey) {
            return;
        }

        event.preventDefault();

        const rect = this.host.nativeElement.getBoundingClientRect();
        const delta = event.deltaMode === WheelEvent.DOM_DELTA_LINE ? event.deltaY * WHEEL_LINE_HEIGHT : event.deltaY;
        const pointer = { x: event.clientX - rect.left, y: event.clientY - rect.top };

        this.canvas.zoomAt(Math.exp(-delta * WHEEL_ZOOM_RATE), pointer);
    }
}
