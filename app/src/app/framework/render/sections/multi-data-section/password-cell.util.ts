/*
* DATAGERRY - OpenSource Enterprise CMDB
* Copyright (C) 2025 becon GmbH
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

/** Returns masked bullets for a password value, or empty string if no value */
export function maskPassword(value: any): string {
    if (value === undefined || value === null) {
        return '';
    }

    const valueAsString = String(value);
    const maskedLength = Math.min(valueAsString.length, 20);
    if (maskedLength === 0) {
        return '';
    }
    return '•'.repeat(maskedLength);
}

/** Returns the display value for a password given visibility */
export function displayPassword(value: any, visible: boolean): string {
    if (value === undefined || value === null || String(value).length === 0) {
        return '';
    }
    return visible ? String(value) : maskPassword(value);
}

// Types
export type PasswordVisibilityMap = { [rowId: number]: { [field: string]: boolean } };

/** Ensure visibility bucket exists for a row */
export function ensureVisibilityBucket(map: PasswordVisibilityMap, rowId: number): void {
    if (!map[rowId]) {
        map[rowId] = {};
    }
}

/** Toggle visibility for a given cell */
export function togglePasswordVisibility(map: PasswordVisibilityMap, rowId: number, fieldName: string): void {
    ensureVisibilityBucket(map, rowId);
    map[rowId][fieldName] = !map[rowId][fieldName];
}

/** Retrieve raw value for field in a given row from a MultiDataSectionEntry structure */
export function getRawValueForFieldFromMds(formatedDataSection: any, multiDataID: number, fieldName: string): any {
    const values = formatedDataSection?.values || [];
    const dataSet = values.filter((dataSet: any) => dataSet.multi_data_id == multiDataID)[0]?.data || [];
    for (let entry of dataSet) {
        if (entry.name === fieldName) {
            return entry.value;
        }
    }
    return undefined;
}

/** Create a new array reference to trigger OnPush change detection */
export function refreshItemsReference<T>(items: T[]): T[] {
    return [...items];
}


