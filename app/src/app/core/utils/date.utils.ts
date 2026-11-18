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
export function getCurrentDate(): string {
    const today = new Date();
    const yyyy = today.getFullYear();
    const mm = String(today.getMonth() + 1).padStart(2, '0');
    const dd = String(today.getDate()).padStart(2, '0');
    return `${yyyy}-${mm}-${dd}`;
  }
  

export interface DateStruct {
    year: number;
    month: number;
    day: number;
}


/** Turns a stored date (`{ $date }`, ISO string or epoch ms) into the struct `app-form-date` reads; UTC, as stored. */
export function toDateStruct(value: unknown): DateStruct | null {
    if (value && typeof value === 'object' && 'year' in value) {
        return value as DateStruct;
    }

    const raw = value && typeof value === 'object' && '$date' in value
        ? (value as { $date: unknown }).$date
        : value;

    if (typeof raw !== 'string' && typeof raw !== 'number') {
        return null;
    }

    const date = new Date(raw);

    if (Number.isNaN(date.getTime())) {
        return null;
    }

    return { year: date.getUTCFullYear(), month: date.getUTCMonth() + 1, day: date.getUTCDate() };
}
