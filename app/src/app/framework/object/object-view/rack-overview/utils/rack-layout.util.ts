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
import {
    RackCapacity,
    RackFace,
    RackRowView,
    RackSlotView,
    RackTypeLegendEntry,
    RackViewSide
} from '../models/rack-overview.types';
/* ------------------------------------------------------------------------------------------------------------------ */

/** Row 1 of the elevation grid is the cabinet cap, so U numbering starts on row 2. */
const FIRST_SLOT_ROW = 2;

/** A rack is counted in fives, so every fifth U is drawn heavier - on the ruler and in the cavity. */
export function isMajorSlot(slot: number): boolean {
    return slot % 5 === 0 || slot === 1;
}


/** Grid row a single U sits on. Slot 1 is the bottom of the rack, row 1 of the grid is its top. */
export function gridRowOfSlot(slot: number, rackHeight: number): string {
    return `${rackHeight - slot + FIRST_SLOT_ROW}`;
}


/** Grid placement of a row: it starts at its anchor slot and spans its height. */
export function gridRowOfPlacement(startSlot: number | null, height: number | null, rackHeight: number): string {
    if (startSlot === null || height === null) {
        return '';
    }

    return `${rackHeight - startSlot + FIRST_SLOT_ROW} / span ${height}`;
}


export function toSlotView(slot: number, rackHeight: number): RackSlotView {
    return { slot, gridRow: gridRowOfSlot(slot, rackHeight), isMajor: isMajorSlot(slot) };
}


/** Lowest slot a row reaches: it is anchored at its start slot and extends downward. */
export function bottomSlotOf(mount: RackRowView): number | null {
    if (mount.startSlot == null || mount.height == null) {
        return null;
    }

    return mount.startSlot - mount.height + 1;
}


/** True when the row has usable geometry that stays inside the rack. */
export function fitsRack(mount: RackRowView, rackHeight: number): boolean {
    const bottom = bottomSlotOf(mount);

    return bottom !== null && mount.startSlot <= rackHeight && bottom >= 1;
}


/** Every slot the row covers, top down. Empty for a row without usable geometry. */
export function slotsCovered(mount: RackRowView): number[] {
    const bottom = bottomSlotOf(mount);

    if (bottom === null) {
        return [];
    }

    return Array.from({ length: mount.height as number }, (_, index) => (mount.startSlot as number) - index);
}


/**
 * Assembles one elevation: the rows that can be drawn on it, the slots left open, and how full it is.
 * Rows whose geometry falls outside the rack are left out here and reported separately.
 */
export function buildFace(
    side: RackViewSide,
    title: string,
    mounts: RackRowView[],
    rackHeight: number
): RackFace {
    const units = mounts.filter(mount => fitsRack(mount, rackHeight));
    const covered = new Set<number>();

    units.forEach(mount => slotsCovered(mount).forEach(slot => covered.add(slot)));

    const freeSlots: RackSlotView[] = [];

    for (let slot = rackHeight; slot >= 1; slot--) {
        if (!covered.has(slot)) {
            freeSlots.push(toSlotView(slot, rackHeight));
        }
    }

    return { side, title, units, freeSlots, capacity: measureCapacity(covered, rackHeight) };
}


/**
 * How full a face is. The largest gap is the longest run of consecutive free slots, which is what tells
 * a user whether the free U can actually take anything - a mount needs them in one piece.
 */
export function measureCapacity(coveredSlots: Set<number>, rackHeight: number): RackCapacity {
    const total = Math.max(rackHeight, 0);
    let used = 0;
    let run = 0;
    let largestGap = 0;

    for (let slot = 1; slot <= total; slot++) {
        if (coveredSlots.has(slot)) {
            used = used + 1;
            run = 0;
            continue;
        }

        run = run + 1;
        largestGap = Math.max(largestGap, run);
    }

    return {
        total,
        used,
        free: total - used,
        percent: total ? Math.round((used / total) * 100) : 0,
        largestGap
    };
}


/** Descending U numbers of a rack, the order a ruler is read in. */
export function buildSlotTicks(rackHeight: number): RackSlotView[] {
    return Array.from({ length: Math.max(rackHeight, 0) }, (_, index) => toSlotView(rackHeight - index, rackHeight));
}


/**
 * Rows that claim slots outside the rack, which happens when the rack height was reduced below an
 * existing placement. They cannot be drawn in the elevation, so they are listed separately.
 */
export function collectOutOfRangeMounts(mounts: RackRowView[], rackHeight: number): RackRowView[] {
    return mounts.filter(mount => !fitsRack(mount, rackHeight));
}


/** Areas without slot geometry are ordered by their explicit position. */
export function sortByPosition(mounts: RackRowView[]): RackRowView[] {
    return [...mounts].sort((first, second) => (first.position ?? 0) - (second.position ?? 0));
}


/**
 * The type legend, heaviest type first. A rack with many types is trimmed to its first entries, so the
 * order decides what a user sees without expanding it.
 */
export function sortTypeLegend(entries: RackTypeLegendEntry[]): RackTypeLegendEntry[] {
    return [...entries].sort((first, second) =>
        second.count - first.count || (first.type_label ?? '').localeCompare(second.type_label ?? ''));
}
