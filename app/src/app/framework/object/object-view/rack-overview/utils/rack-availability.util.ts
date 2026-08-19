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
import { slotRangeText } from './rack-layout.util';
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
 * One entry of the start slot list: either an anchor the row can be placed at, or a whole stretch of
 * U that cannot take it, collapsed into a single line.
 */
export interface RackSlotOption {
    /** Top U of the entry, which is the anchor a placement writes. */
    slot: number;
    /** The U range the row would occupy, or the blocked stretch and why it is blocked. */
    label: string;
    disabled: boolean;
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


/**
 * Whether a row of this height can be anchored at a slot: the free stretch below the anchor has to
 * swallow the whole span, not just the anchor itself.
 */
export function fitsAt(runs: RackFreeRun[], slot: number, height: number): boolean {
    const run = runContaining(runs, slot);

    return run !== null && slot - run.from + 1 >= Math.max(height, 1);
}


/**
 * The area read top down - the order an elevation is read in - as the placements it offers.
 *
 * Every U the row can be anchored at is its own entry, labelled with the range a row of `height` would
 * occupy from there. The U that cannot take it are kept rather than dropped, so the list still covers
 * the whole area, but a stretch of them collapses into one disabled line - five taken U in a row read
 * as `U25-U21 in use`, not as five entries saying the same thing. A stretch ends where the reason
 * changes, so slots held by a row are never folded together with free ones a tall row outgrows.
 */
export function slotOptions(runs: RackFreeRun[], rackHeight: number, height: number): RackSlotOption[] {
    const span = Math.max(height, 1);
    const options: RackSlotOption[] = [];

    /** The blocked stretch being collected: where it starts, and whether it is held by a row. */
    let blocked: { top: number; taken: boolean } | null = null;

    const closeBlocked = (bottom: number) => {
        if (!blocked) {
            return;
        }

        const size = blocked.top - bottom + 1;
        // A free stretch that is only too short says how short: its own length is the room it leaves.
        const reason = blocked.taken ? 'in use' : `only ${size}U free`;

        options.push({
            slot: blocked.top,
            label: `${slotRangeText(blocked.top, size)} \u00b7 ${reason}`,
            disabled: true
        });

        blocked = null;
    };

    for (let slot = rackHeight; slot >= 1; slot--) {
        if (fitsAt(runs, slot, span)) {
            closeBlocked(slot + 1);
            options.push({ slot, label: slotRangeText(slot, span), disabled: false });
            continue;
        }

        const taken = runContaining(runs, slot) === null;

        if (blocked && blocked.taken !== taken) {
            closeBlocked(slot + 1);
        }

        blocked = blocked ?? { top: slot, taken };
    }

    closeBlocked(1);

    return options;
}
