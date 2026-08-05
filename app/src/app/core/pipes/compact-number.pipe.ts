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
import { Pipe, PipeTransform } from '@angular/core';

/**
 * Suffixes for short-scale powers of one thousand, from thousand up to
 * undecillion. This covers values up to 2^128 (~3.4e38), which falls within the
 * undecillion tier, so even IPv6 address counts stay within the named suffixes.
 */
const COMPACT_SUFFIXES = ['', 'K', 'M', 'B', 'T', 'Qa', 'Qi', 'Sx', 'Sp', 'Oc', 'No', 'Dc', 'Ud'];

/**
 * Formats a large number into a compact, suffixed form (e.g. 1.5 K, 79.23 Oc).
 * Useful for counts that exceed JavaScript's safe integer range and arrive as
 * approximate floats. Values below 1000 are shown as-is; anything beyond the
 * largest named suffix falls back to scientific notation.
 */
@Pipe({
    name: 'compactNumber',
    standalone: false
})
export class CompactNumberPipe implements PipeTransform {

    public transform(value: number | string | null | undefined): string {
        if (value === null || value === undefined || value === '') {
            return '–';
        }

        const numeric = Number(value);
        if (!Number.isFinite(numeric)) {
            return '–';
        }

        const sign = numeric < 0 ? '-' : '';
        let magnitude = Math.abs(numeric);

        if (magnitude < 1000) {
            return sign + Math.round(magnitude).toString();
        }

        let tier = 0;
        while (magnitude >= 1000 && tier < COMPACT_SUFFIXES.length - 1) {
            magnitude /= 1000;
            tier++;
        }

        if (magnitude >= 1000) {
            return sign + numeric.toExponential(2);
        }

        const formatted = magnitude.toFixed(2).replace(/\.?0+$/, '');
        return `${sign}${formatted} ${COMPACT_SUFFIXES[tier]}`;
    }
}
