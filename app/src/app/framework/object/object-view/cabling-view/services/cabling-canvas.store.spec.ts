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
import { TestBed } from '@angular/core/testing';

import { CABLING_ZOOM } from '../constants/cabling.constants';
import { CablingCanvasStore } from './cabling-canvas.store';

describe('CablingCanvasStore', () => {
    let canvas: CablingCanvasStore;
    let frame: HTMLElement;

    beforeEach(() => {
        TestBed.configureTestingModule({ providers: [CablingCanvasStore] });
        canvas = TestBed.inject(CablingCanvasStore);

        frame = document.createElement('div');
        frame.style.cssText = 'position: fixed; top: 0; left: 0; width: 1000px; height: 600px;';
        document.body.appendChild(frame);
        canvas.attach(frame);
    });

    afterEach(() => frame.remove());

    it('eases a keyboard pan, and follows a gesture without easing', () => {
        canvas.panBy(48, 0);

        expect(canvas.viewport()).toEqual({ x: 48, y: 0, zoom: 1 });
        expect(canvas.animate()).toBeTrue();

        canvas.startGesture();
        canvas.panTo(100, 20);

        expect(canvas.viewport()).toEqual({ x: 100, y: 20, zoom: 1 });
        expect(canvas.animate()).toBeFalse();
        expect(canvas.isPanning()).toBeTrue();
    });

    it('zooms a step around the middle of the frame', () => {
        canvas.zoomIn();

        expect(canvas.viewport().zoom).toBe(CABLING_ZOOM.step);
        expect(canvas.viewport().x).toBeCloseTo(500 - 500 * CABLING_ZOOM.step);
        expect(canvas.viewport().y).toBeCloseTo(300 - 300 * CABLING_ZOOM.step);
    });

    it('stops zooming at either limit', () => {
        expect(canvas.canZoomIn()).toBeTrue();
        expect(canvas.canZoomOut()).toBeTrue();

        for (let step = 0; step < 20; step++) {
            canvas.zoomIn();
        }

        expect(canvas.viewport().zoom).toBe(CABLING_ZOOM.max);
        expect(canvas.canZoomIn()).toBeFalse();
        expect(canvas.canZoomOut()).toBeTrue();

        for (let step = 0; step < 20; step++) {
            canvas.zoomOut();
        }

        expect(canvas.viewport().zoom).toBe(CABLING_ZOOM.min);
        expect(canvas.canZoomOut()).toBeFalse();
        expect(canvas.canZoomIn()).toBeTrue();
    });

    it('moves to a revealed card only when it is off screen, centring the cards around it', () => {
        const onScreen = { minX: 10, minY: 10, maxX: 100, maxY: 100 };
        const offScreen = { minX: 2000, minY: 0, maxX: 2100, maxY: 100 };

        canvas.reveal(onScreen, onScreen);

        expect(canvas.viewport()).toEqual({ x: 0, y: 0, zoom: 1 });

        canvas.reveal(offScreen, { minX: 1900, minY: 0, maxX: 2100, maxY: 100 });

        expect(canvas.viewport()).toEqual({ x: 500 - 2000, y: 300 - 50, zoom: 1 });
    });

    it('keeps where cards were dragged to until they are reset', () => {
        canvas.moveCard(7, { x: 5, y: 6 });

        expect(canvas.offsets().get(7)).toEqual({ x: 5, y: 6 });

        canvas.resetCards();

        expect(canvas.offsets().size).toBe(0);
    });

    it('remembers that a gesture moved, for the click that follows it', () => {
        canvas.startGesture();
        canvas.endGesture(true);

        expect(canvas.dragged).toBeTrue();
        expect(canvas.isPanning()).toBeFalse();
    });
});
