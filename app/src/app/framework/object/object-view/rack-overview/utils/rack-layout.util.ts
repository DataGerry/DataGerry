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
import { RackMountRow, RackSlotRow } from '../models/rack-overview.types';
/* ------------------------------------------------------------------------------------------------------------------ */

/** Lowest slot a mount reaches: it is anchored at its start slot and extends downward. */
export function bottomSlotOf(mount: RackMountRow): number | null {
    if (mount.start_slot == null || mount.height == null) {
        return null;
    }

    return mount.start_slot - mount.height + 1;
}


/** True when the mount has usable geometry that stays inside the rack. */
export function fitsRack(mount: RackMountRow, rackHeight: number): boolean {
    const bottom = bottomSlotOf(mount);

    return bottom !== null && mount.start_slot <= rackHeight && bottom >= 1;
}


/**
 * Builds the rows of one rack side, top slot first. A mount is emitted once at its anchor and spans
 * its height; the slots it covers below the anchor are consumed by that span and not emitted again.
 */
export function buildSlotRows(mounts: RackMountRow[], rackHeight: number): RackSlotRow[] {
    const anchors = new Map<number, RackMountRow>();
    const covered = new Set<number>();

    for (const mount of mounts) {
        if (!fitsRack(mount, rackHeight)) {
            continue;
        }

        const top = mount.start_slot as number;
        const bottom = bottomSlotOf(mount) as number;

        anchors.set(top, mount);

        for (let slot = bottom; slot <= top; slot++) {
            covered.add(slot);
        }
    }

    const rows: RackSlotRow[] = [];

    for (let slot = rackHeight; slot >= 1; slot--) {
        const mount = anchors.get(slot);

        if (mount) {
            rows.push({ slot, span: mount.height as number, mount });
            continue;
        }

        if (!covered.has(slot)) {
            rows.push({ slot, span: 1, mount: null });
        }
    }

    return rows;
}


/**
 * Mounts that claim slots outside the rack, which happens when the rack height was reduced below an
 * existing placement. They cannot be drawn in the grid, so they are listed separately.
 */
export function collectOutOfRangeMounts(mounts: RackMountRow[], rackHeight: number): RackMountRow[] {
    return mounts.filter(mount => !fitsRack(mount, rackHeight));
}


/** Areas without slot geometry are ordered by their explicit position. */
export function sortByPosition(mounts: RackMountRow[]): RackMountRow[] {
    return [...mounts].sort((first, second) => (first.position ?? 0) - (second.position ?? 0));
}
