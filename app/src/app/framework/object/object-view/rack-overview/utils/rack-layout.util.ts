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
import { RackCapacity, RackFace, RackMountRow, RackViewSide } from '../models/rack-overview.types';
/* ------------------------------------------------------------------------------------------------------------------ */

/** Lowest slot a row reaches: it is anchored at its start slot and extends downward. */
export function bottomSlotOf(mount: RackMountRow): number | null {
    if (mount.start_slot == null || mount.height == null) {
        return null;
    }

    return mount.start_slot - mount.height + 1;
}


/** True when the row has usable geometry that stays inside the rack. */
export function fitsRack(mount: RackMountRow, rackHeight: number): boolean {
    const bottom = bottomSlotOf(mount);

    return bottom !== null && mount.start_slot <= rackHeight && bottom >= 1;
}


/** Every slot the row covers, top down. Empty for a row without usable geometry. */
export function slotsCovered(mount: RackMountRow): number[] {
    const bottom = bottomSlotOf(mount);

    if (bottom === null) {
        return [];
    }

    return Array.from({ length: mount.height as number }, (_, index) => (mount.start_slot as number) - index);
}


/**
 * Assembles one elevation: the rows that can be drawn on it, the slots left open, and how full it is.
 * Rows whose geometry falls outside the rack are left out here and reported separately.
 */
export function buildFace(
    side: RackViewSide,
    title: string,
    mounts: RackMountRow[],
    rackHeight: number
): RackFace {
    const units = mounts.filter(mount => fitsRack(mount, rackHeight));
    const covered = new Set<number>();

    units.forEach(mount => slotsCovered(mount).forEach(slot => covered.add(slot)));

    const freeSlots: number[] = [];

    for (let slot = rackHeight; slot >= 1; slot--) {
        if (!covered.has(slot)) {
            freeSlots.push(slot);
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
export function buildSlotTicks(rackHeight: number): number[] {
    return Array.from({ length: Math.max(rackHeight, 0) }, (_, index) => rackHeight - index);
}


/**
 * Rows that claim slots outside the rack, which happens when the rack height was reduced below an
 * existing placement. They cannot be drawn in the elevation, so they are listed separately.
 */
export function collectOutOfRangeMounts(mounts: RackMountRow[], rackHeight: number): RackMountRow[] {
    return mounts.filter(mount => !fitsRack(mount, rackHeight));
}


/** Areas without slot geometry are ordered by their explicit position. */
export function sortByPosition(mounts: RackMountRow[]): RackMountRow[] {
    return [...mounts].sort((first, second) => (first.position ?? 0) - (second.position ?? 0));
}
