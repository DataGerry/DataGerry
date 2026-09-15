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
import { RackArea, RackMountUpdatePayload, RackRowView, RackViewSide } from './rack-overview.types';
/* ------------------------------------------------------------------------------------------------------------------ */


/**
 * The row currently in flight. The height is resolved here rather than read off the row each time,
 * because a staged entry may carry none and still has to be given slots when it lands.
 */
export interface RackDragSource {
    mount: RackRowView;
    height: number;
    /** Which U of the grabbed plate the drag started on, counted from its top. */
    grabOffset: number;
}


/**
 * What kind of target the drag points at: a U on one of the faces, or one of the cards beside the
 * drawing. Stated rather than inferred from whichever field happens to be empty.
 */
export type RackDropTarget = 'slot' | 'area';


/**
 * Where the drag would land, resolved into the placement the update route is given plus what the
 * preview says about it. One label carries both readings: the U range when the drop is free, and the
 * reason it is refused when it is not.
 */
export interface RackDropPlan {
    target: RackDropTarget;
    area: RackArea;
    /** Null for a drop that takes the row out of the elevation. */
    startSlot: number | null;
    /** The faces the preview is drawn on. A full depth row claims both. */
    sides: RackViewSide[];
    gridRow: string;
    label: string;
    ok: boolean;
    /** What the drop would write. Built with the plan, so nothing has to derive it again on commit. */
    payload: RackMountUpdatePayload;
}


/** A plan resolved to one face of the elevation, which is what the template draws. */
export interface RackDropBand {
    side: RackViewSide;
    isRear: boolean;
    gridRow: string;
    label: string;
    ok: boolean;
}
