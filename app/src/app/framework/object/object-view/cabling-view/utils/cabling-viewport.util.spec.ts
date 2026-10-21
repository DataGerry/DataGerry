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
import { CABLING_FIT_INSETS, CABLING_ZOOM } from '../constants/cabling.constants';
import {
    canvasToScreen,
    centerViewport,
    clampZoom,
    containsBounds,
    fitViewport,
    screenToCanvas,
    visibleCanvas,
    zoomAround
} from './cabling-viewport.util';

describe('cabling-viewport.util', () => {
    const size = { width: 1000, height: 600 };

    it('keeps zoom inside its bounds', () => {
        expect(clampZoom(10)).toBe(CABLING_ZOOM.max);
        expect(clampZoom(0.01)).toBe(CABLING_ZOOM.min);
        expect(clampZoom(1.1)).toBe(1.1);
    });

    it('zooms without moving the canvas point under the pointer', () => {
        const before = { x: 40, y: -20, zoom: 1 };
        const pointer = { x: 300, y: 200 };
        const after = zoomAround(before, 2, pointer);
        const canvasPoint = (viewport: typeof before) =>
            ({ x: (pointer.x - viewport.x) / viewport.zoom, y: (pointer.y - viewport.y) / viewport.zoom });

        expect(after.zoom).toBe(2);
        expect(canvasPoint(after)).toEqual(canvasPoint(before));
    });

    it('fits a small drawing at its natural size, centred in the room the toolbar leaves', () => {
        const fitted = fitViewport({ minX: 0, minY: 0, maxX: 200, maxY: 100 }, size, { x: 0, y: 0, zoom: 0.5 });
        const { top, bottom } = CABLING_FIT_INSETS;

        expect(fitted).toEqual({ x: 400, y: top + (size.height - top - bottom) / 2 - 50, zoom: 1 });
    });

    it('shrinks a wide drawing until it fits inside the padding', () => {
        const fitted = fitViewport({ minX: 0, minY: 0, maxX: 2000, maxY: 100 }, size, { x: 0, y: 0, zoom: 1 });
        const shown = visibleCanvas(fitted, size);

        expect(fitted.zoom).toBeLessThan(1);
        expect(containsBounds(shown, { minX: 0, minY: 0, maxX: 2000, maxY: 100 })).toBeTrue();
    });

    it('leaves the view alone while there is nothing to fit or no room to fit it in', () => {
        const current = { x: 5, y: 6, zoom: 0.8 };

        expect(fitViewport(null, size, current)).toBe(current);
        expect(fitViewport({ minX: 0, minY: 0, maxX: 10, maxY: 10 }, { width: 0, height: 0 }, current)).toBe(current);
    });

    it('centres a canvas point and reads the same point back as the middle of the screen', () => {
        const viewport = centerViewport({ x: 120, y: 80 }, size, 1.5);
        const shown = visibleCanvas(viewport, size);

        expect((shown.minX + shown.maxX) / 2).toBeCloseTo(120);
        expect((shown.minY + shown.maxY) / 2).toBeCloseTo(80);
    });

    it('converts between screen and canvas points both ways', () => {
        const viewport = { x: 40, y: -20, zoom: 2 };

        expect(canvasToScreen({ x: 10, y: 30 }, viewport)).toEqual({ x: 60, y: 40 });
        expect(screenToCanvas({ x: 60, y: 40 }, viewport)).toEqual({ x: 10, y: 30 });
    });
});
