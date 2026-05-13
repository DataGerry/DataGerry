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
import { IpamTypeDistributionEntry } from '../../models/ipam-overview.types';
/* ------------------------------------------------------------------------------------------------------------------ */

const RESERVED_COLORS: Readonly<Record<string, string>> = {
    free: '#B5BBC4',
    unknown: '#9CA3AF'
};

const DYNAMIC_PALETTE: ReadonlyArray<string> = [
    '#3B82F6',
    '#10B981',
    '#F59E0B',
    '#EF4444',
    '#8B5CF6',
    '#EC4899',
    '#14B8A6',
    '#F97316',
    '#6366F1',
    '#22C55E'
];

export function getTypeDistributionColors(items: IpamTypeDistributionEntry[]): string[] {
    let paletteIndex = 0;

    return items.map(item => {
        const reserved = RESERVED_COLORS[item.label?.toLowerCase()];
        if (reserved) {
            return reserved;
        }

        const color = DYNAMIC_PALETTE[paletteIndex % DYNAMIC_PALETTE.length];
        paletteIndex += 1;
        return color;
    });
}
