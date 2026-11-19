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

import { FieldChangeEntry, FieldChangeRow } from './object-log-change-view.types';
/* ------------------------------------------------------------------------------------------------------------------ */

/** The diff only lists changed entries, so a field added or removed by the save sits on one side only. */
export function pairByFieldName(oldEntries: FieldChangeEntry[], newEntries: FieldChangeEntry[]): FieldChangeRow[] {
    const oldByName = new Map(oldEntries.map(entry => [entry.name, entry]));
    const newByName = new Map(newEntries.map(entry => [entry.name, entry]));
    const names = [...new Set([...oldByName.keys(), ...newByName.keys()])].sort();

    return names.map(name => {
        const oldValue = oldByName.get(name)?.value;
        const newValue = newByName.get(name)?.value;

        return {
            name,
            oldValue,
            newValue,
            added: !oldByName.has(name),
            removed: !newByName.has(name),
            oldEmpty: isEmptyValue(oldValue),
            newEmpty: isEmptyValue(newValue),
        };
    });
}

/** Values that would otherwise render as blank text. */
export function isEmptyValue(value: unknown): boolean {
    return value === null || value === undefined || value === '' || (Array.isArray(value) && value.length === 0);
}
