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
import { CablingAnchorSide, CablingEdge, CablingNodeLayout, CablingPoint } from './cabling.types';
/* ------------------------------------------------------------------------------------------------------------------ */

export type CablingRouteKind = 'curve' | 'bracket' | 'passage' | 'hook';


/** One end of a cable on the canvas: its card, the anchor on that card and the face it leaves by. */
export interface CablingEdgeEnd {
    node: CablingNodeLayout;
    point: CablingPoint;
    side: CablingAnchorSide;
}


export interface CablingEdgePlan {
    edge: CablingEdge;
    from: CablingEdgeEnd;
    to: CablingEdgeEnd;
    kind: CablingRouteKind;
}


export interface CablingRoute {
    path: string;
    labelAt: CablingPoint;
}


/** A cable turning back around its own card: how far it bows out, and the level it runs back on. */
export interface CablingHook {
    bulge: number;
    level: number;
}


/** One end of a hooked cable, grouped with the other hooks along the same card edge. */
export interface CablingTurn {
    key: string;
    end: CablingEdgeEnd;
    other: CablingEdgeEnd;
    below: boolean;
}


/** Where a cable's middle curve meets one end, past the hook that leads there from the port. */
export interface CablingExit {
    point: CablingPoint;
    heading: number;
    out: string;
    back: string;
}
