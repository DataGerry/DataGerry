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
import { RackDragSource, RackDropPlan, RackDropTarget } from '../models/rack-dnd.types';
import {
    RACK_OCCUPANT_FORBIDDEN_AREAS,
    RackArea,
    RackRowView,
    RackViewSide
} from '../models/rack-overview.types';
import { gridRowOfPlacement, slotRangeText, slotsOf } from './rack-layout.util';
/* ------------------------------------------------------------------------------------------------------------------ */

/**
 * What a refused drop says instead of a U range. Most are read off the preview band, in the drawing,
 * so each one has to make sense at a glance and at plate width.
 */
export const RACK_DROP_REASON = {
    overlap: 'Slots taken',
    tooTall: 'Taller than the rack',
    noHeight: 'No rack height set',
    alreadyThere: 'Already here',
    objectsOnly: 'This area holds objects only'
} as const;

/** What each area without slot geometry offers the row in flight. */
const AREA_DROP_LABEL: Partial<Record<RackArea, string>> = {
    [RackArea.LEFT]: 'Mount on the left side',
    [RackArea.RIGHT]: 'Mount on the right side',
    [RackArea.UNASSIGNED]: 'Take out of the elevation'
};


/**
 * Which U of a face the pointer sits over. The band is drawn top down and slot 1 is the bottom of the
 * rack, so the row index counts the other way. Coordinates are read from the measured band rather than
 * from the U token, which keeps the maths right at any zoom factor.
 */
export function slotAtPoint(clientY: number, band: DOMRect, rackHeight: number): number | null {
    if (rackHeight < 1 || band.height <= 0) {
        return null;
    }

    const index = Math.floor(((clientY - band.top) / band.height) * rackHeight);

    return rackHeight - clamp(index, 0, rackHeight - 1);
}


/** A row that carries no height still has to be given slots when it lands, and one U is the least. */
export function dragHeightOf(mount: RackRowView): number {
    return Math.max(mount.height ?? 1, 1);
}


/** Which U of the grabbed plate the drag started on, counted from its top. */
export function grabOffsetIn(plate: DOMRect, clientY: number, height: number): number {
    if (plate.height <= 0 || height < 2) {
        return 0;
    }

    return clamp(Math.floor(((clientY - plate.top) / plate.height) * height), 0, height - 1);
}


/**
 * The anchor the row would take. The grabbed U stays under the cursor, and a result that would hang
 * out of the enclosure is pulled back in rather than refused - dragging towards an edge should land on
 * the nearest place that fits, not on nothing.
 */
export function anchorForDrop(hoveredSlot: number, source: RackDragSource, rackHeight: number): number {
    return clamp(hoveredSlot + source.grabOffset, source.height, rackHeight);
}


/**
 * The slots one face already holds, ignoring the row being moved. A full depth row holds both faces.
 * A null id excludes nothing, which is what adding a new row needs.
 */
export function occupiedSlots(rows: RackRowView[], side: RackViewSide, movedMountId: number | null): Set<number> {
    const taken = new Set<number>();

    for (const row of rows) {
        if (row.mountId === movedMountId || (row.area !== side && row.area !== RackArea.FULL_DEPTH)) {
            continue;
        }

        for (const slot of slotsOf(row.startSlot, row.height)) {
            taken.add(slot);
        }
    }

    return taken;
}


/**
 * Resolves a drag over a face into the placement a drop would write, and whether the slots are free.
 * A full depth row keeps its depth wherever it is dropped - changing that is a decision for the form,
 * not something a drag should do behind the user's back - so it is checked against both faces.
 */
export function planSlotDrop(
    source: RackDragSource,
    side: RackViewSide,
    hoveredSlot: number,
    rows: RackRowView[],
    rackHeight: number
): RackDropPlan {
    const area = source.mount.isFullDepth ? RackArea.FULL_DEPTH : side;
    const sides: RackViewSide[] = source.mount.isFullDepth ? [RackArea.FRONT, RackArea.BACK] : [side];

    // Nothing is drawn without a height, so there is also nothing to refuse it against.
    if (rackHeight < 1) {
        return refusedPlan('slot', area, sides, RACK_DROP_REASON.noHeight, '');
    }

    // The row is longer than the enclosure, so no anchor exists and the whole cavity is refused.
    if (source.height > rackHeight) {
        const wholeRack = gridRowOfPlacement(rackHeight, rackHeight, rackHeight);

        return refusedPlan('slot', area, sides, RACK_DROP_REASON.tooTall, wholeRack);
    }

    const startSlot = anchorForDrop(hoveredSlot, source, rackHeight);
    const wanted = slotsOf(startSlot, source.height);

    const isBlocked = sides.some((face) => {
        const taken = occupiedSlots(rows, face, source.mount.mountId);

        return wanted.some(slot => taken.has(slot));
    });

    return {
        target: 'slot',
        area,
        startSlot,
        sides,
        gridRow: gridRowOfPlacement(startSlot, source.height, rackHeight),
        label: isBlocked ? RACK_DROP_REASON.overlap : slotRangeText(startSlot, source.height),
        ok: !isBlocked,
        // The unused axis is cleared, so a move out of a side rail cannot leave a stale ordering behind.
        payload: { area, start_slot: startSlot, height: source.height, position: null }
    };
}


/**
 * A drag over one of the cards beside the drawing: a side rail, or the staging tray. None of them has
 * slot geometry, so the row simply gives up the slots it held and the backend appends it to the area.
 */
export function planAreaDrop(source: RackDragSource, area: RackArea): RackDropPlan {
    if (source.mount.area === area) {
        return refusedPlan('area', area, [], RACK_DROP_REASON.alreadyThere, '');
    }

    // A reservation or a blocker holds space; only an object can be bolted to the side of a rack.
    if (!source.mount.isMount && RACK_OCCUPANT_FORBIDDEN_AREAS.includes(area)) {
        return refusedPlan('area', area, [], RACK_DROP_REASON.objectsOnly, '');
    }

    // The tray keeps the height as the hint a later placement is pre-filled from; a rail has no use for it.
    const height = area === RackArea.UNASSIGNED ? source.height : null;

    return {
        target: 'area',
        area,
        startSlot: null,
        sides: [],
        gridRow: '',
        label: AREA_DROP_LABEL[area] ?? '',
        ok: true,
        payload: { area, start_slot: null, height }
    };
}


/** True when the plan would write back exactly where the row already sits, which is nothing to save. */
export function isSamePlacement(source: RackDragSource, plan: RackDropPlan): boolean {
    return source.mount.area === plan.area && source.mount.startSlot === plan.startSlot;
}


/**
 * Plans compare by where they land, not by identity. A drag reports a position on every pixel it
 * crosses but changes the slot it points at far more rarely, so this is what keeps the preview from
 * being rebuilt and rewritten on each of them. It does not stop the change detection pass itself -
 * a bound dragover marks the view either way - only the work behind it.
 *
 * The remaining fields are all derived from the three compared here, so equal plans also read alike.
 */
export function isSamePlan(first: RackDropPlan | null, second: RackDropPlan | null): boolean {
    if (first === second) {
        return true;
    }

    if (!first || !second) {
        return false;
    }

    return first.area === second.area && first.startSlot === second.startSlot && first.ok === second.ok;
}

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

function clamp(value: number, min: number, max: number): number {
    return Math.min(Math.max(value, min), max);
}


/** A plan that is only ever drawn, never written, so it carries no payload of its own. */
function refusedPlan(
    target: RackDropTarget,
    area: RackArea,
    sides: RackViewSide[],
    label: string,
    gridRow: string
): RackDropPlan {
    return { target, area, startSlot: null, sides, gridRow, label, ok: false, payload: {} };
}
