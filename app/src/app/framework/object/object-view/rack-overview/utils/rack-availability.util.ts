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
import { RACK_SLOT_AREAS, RackArea, RackRowView, RackViewSide } from '../models/rack-overview.types';
import { occupiedSlots } from './rack-drop-rules';
/* ------------------------------------------------------------------------------------------------------------------ */

/**
 * An unbroken stretch of free U on a face. A row has to fit into one of these in one piece, so the
 * run - not the free total - is what decides whether a height can be placed at all.
 */
export interface RackFreeRun {
    /** Lowest U of the stretch. */
    from: number;
    /** Highest U of the stretch, and the anchor a row takes when it is placed at the top of it. */
    to: number;
    size: number;
}


/**
 * How much room an area still has. `largestRun` is the honest number: twelve free U spread over four
 * gaps cannot take a 3U server, and only the run says so.
 */
export interface RackAreaSpace {
    free: number;
    largestRun: number;
}


/**
 * The faces an area competes for, mirroring the backend's conflict map: a front placement competes
 * with the front and with every full depth row, and a full depth placement competes with both faces
 * because it holds the same U range in each.
 */
function facesOf(area: RackArea): RackViewSide[] {
    if (area === RackArea.FULL_DEPTH) {
        return [RackArea.FRONT, RackArea.BACK];
    }

    return area === RackArea.BACK ? [RackArea.BACK] : [RackArea.FRONT];
}


/**
 * The stretches of free U an area still offers, top down - the order the elevation is read in.
 *
 * `excludeMountId` drops the row being edited from its own comparison, so re-slotting a row does not
 * collide with where it currently sits. Pass null when a new row is being added.
 */
export function freeRuns(
    rows: RackRowView[],
    area: RackArea,
    rackHeight: number,
    excludeMountId: number | null
): RackFreeRun[] {
    if (!RACK_SLOT_AREAS.includes(area) || rackHeight < 1) {
        return [];
    }

    const taken = new Set<number>();

    for (const face of facesOf(area)) {
        for (const slot of occupiedSlots(rows, face, excludeMountId)) {
            taken.add(slot);
        }
    }

    const runs: RackFreeRun[] = [];
    let bottom: number | null = null;

    // Counted upward so a run is closed at its highest U, which is the anchor a row placed in it takes.
    for (let slot = 1; slot <= rackHeight; slot++) {
        if (!taken.has(slot)) {
            bottom = bottom ?? slot;
            continue;
        }

        if (bottom !== null) {
            runs.push({ from: bottom, to: slot - 1, size: slot - bottom });
            bottom = null;
        }
    }

    if (bottom !== null) {
        runs.push({ from: bottom, to: rackHeight, size: rackHeight - bottom + 1 });
    }

    return runs.reverse();
}


/** The runs a row of this height still fits into, in the order `freeRuns` reports them. */
export function runsThatFit(runs: RackFreeRun[], height: number): RackFreeRun[] {
    return height > 0 ? runs.filter(run => run.size >= height) : runs;
}


/** Free U and longest unbroken stretch of an area, for the capacity read-out on the area itself. */
export function measureArea(
    rows: RackRowView[],
    area: RackArea,
    rackHeight: number,
    excludeMountId: number | null
): RackAreaSpace {
    const runs = freeRuns(rows, area, rackHeight, excludeMountId);

    return {
        free: runs.reduce((total, run) => total + run.size, 0),
        largestRun: runs.reduce((largest, run) => Math.max(largest, run.size), 0)
    };
}


/** The run a slot falls into, or null when the slot is already taken. */
export function runContaining(runs: RackFreeRun[], slot: number): RackFreeRun | null {
    return runs.find(run => slot >= run.from && slot <= run.to) ?? null;
}
