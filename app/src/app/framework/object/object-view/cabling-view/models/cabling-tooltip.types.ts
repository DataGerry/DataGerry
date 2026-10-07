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
import { CablingViewport } from './cabling-viewport.types';
/* ------------------------------------------------------------------------------------------------------------------ */

/** One end of the hovered cable, named the way its card names it. */
export interface CablingTooltipEnd {
    title: string;
    port: string | null;
    /** Front or Rear, when the port name does not already say it. */
    side: string | null;
    restricted: boolean;
}


/** What the cable tooltip shows. */
export interface CablingCableTooltip {
    connectionId: number;
    title: string;
    stroke: string;
    /** Type, length and colour on one line; null when the cable has none of them. */
    details: string | null;
    description: string | null;
    /** Left to right, as the canvas draws them. */
    ends: [CablingTooltipEnd, CablingTooltipEnd];
}


/** The spot on the cable the tooltip points at, in screen pixels on the frame. */
export interface CablingTooltipPlacement {
    x: number;
    y: number;
    /** The bubble's left edge, measured from the spot. */
    offset: number;
    /** The arrow's position, measured from the bubble's left edge. */
    arrow: number;
    below: boolean;
}


/** The cable under the pointer, placed for the viewport it was hovered in. */
export interface CablingCableHover {
    connectionId: number;
    placement: CablingTooltipPlacement;
    viewport: CablingViewport;
}


/** A tooltip ready to draw. */
export interface CablingTooltipView {
    content: CablingCableTooltip;
    placement: CablingTooltipPlacement;
}


/** A point on a path, `length` canvas pixels from its start. */
export interface CablingPathSample {
    length: number;
    x: number;
    y: number;
}


/** The hovered path, sampled once while the pointer stays on it. */
export interface CablingPathProbe {
    path: SVGGeometryElement;
    d: string | null;
    samples: CablingPathSample[];
}
