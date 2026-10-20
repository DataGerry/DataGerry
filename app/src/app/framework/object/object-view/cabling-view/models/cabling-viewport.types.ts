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
import { CablingPoint } from './cabling.types';
/* ------------------------------------------------------------------------------------------------------------------ */

/** Pan in screen pixels, zoom as a factor; a canvas point p lands on screen at p * zoom + pan. */
export interface CablingViewport {
    x: number;
    y: number;
    zoom: number;
}


export interface CablingSize {
    width: number;
    height: number;
}


/** A press on the canvas, followed until release: a pan, or a card being dragged. */
export interface CablingGesture {
    kind: 'pan' | 'node';
    pointerId: number;
    objectId: number | null;
    startX: number;
    startY: number;
    origin: CablingPoint;
    moved: boolean;
}
