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
import { CablingSize, CablingViewport } from '../models/cabling-viewport.types';
import { CablingBounds, CablingPoint } from '../models/cabling.types';
/* ------------------------------------------------------------------------------------------------------------------ */

export function clampZoom(zoom: number): number {
    return Math.min(CABLING_ZOOM.max, Math.max(CABLING_ZOOM.min, zoom));
}


/** Zooms while keeping the canvas point under `screenPoint` where it is. */
export function zoomAround(viewport: CablingViewport, zoom: number, screenPoint: CablingPoint): CablingViewport {
    const next = clampZoom(zoom);
    const ratio = next / viewport.zoom;

    return {
        x: screenPoint.x - (screenPoint.x - viewport.x) * ratio,
        y: screenPoint.y - (screenPoint.y - viewport.y) * ratio,
        zoom: next
    };
}


/** Shows the whole drawing inside the insets, never enlarged past its natural size. */
export function fitViewport(bounds: CablingBounds | null, size: CablingSize, current: CablingViewport): CablingViewport {
    if (!bounds || size.width <= 0 || size.height <= 0) {
        return current;
    }

    const { top, right, bottom, left } = CABLING_FIT_INSETS;
    const room = { width: Math.max(1, size.width - left - right), height: Math.max(1, size.height - top - bottom) };
    const contentWidth = Math.max(1, bounds.maxX - bounds.minX);
    const contentHeight = Math.max(1, bounds.maxY - bounds.minY);
    const zoom = clampZoom(Math.min(1, room.width / contentWidth, room.height / contentHeight));
    const centred = centerViewport({ x: (bounds.minX + bounds.maxX) / 2, y: (bounds.minY + bounds.maxY) / 2 }, room, zoom);

    return { ...centred, x: centred.x + left, y: centred.y + top };
}


/** Puts a canvas point in the middle of the screen. */
export function centerViewport(point: CablingPoint, size: CablingSize, zoom: number): CablingViewport {
    return { x: size.width / 2 - point.x * zoom, y: size.height / 2 - point.y * zoom, zoom };
}


/** The part of the canvas on screen, in canvas coordinates. */
export function visibleCanvas(viewport: CablingViewport, size: CablingSize): CablingBounds {
    return {
        minX: -viewport.x / viewport.zoom,
        minY: -viewport.y / viewport.zoom,
        maxX: (size.width - viewport.x) / viewport.zoom,
        maxY: (size.height - viewport.y) / viewport.zoom
    };
}


export function containsBounds(outer: CablingBounds, inner: CablingBounds): boolean {
    return inner.minX >= outer.minX && inner.maxX <= outer.maxX && inner.minY >= outer.minY && inner.maxY <= outer.maxY;
}
