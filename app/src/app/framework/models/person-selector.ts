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

export type PersonKind = 'PERSON' | 'PERSON_GROUP';

export const PERSON_KINDS: ReadonlyArray<PersonKind> = ['PERSON', 'PERSON_GROUP'];

/** One selectable or selected person / person group, as the backend renders it. */
export interface PersonSelection {
    object_id: number;
    type_id: number;
    type_label: string;
    kind: PersonKind;
    label: string | null;
}

/** Stored value of a person field: one id (or null), or a list of ids when the field allows several. */
export type PersonFieldValue = number | number[] | null;

export interface PersonPickerQuery {
    kinds?: ReadonlyArray<PersonKind>;
    search?: string;
    ids?: ReadonlyArray<number>;
    page?: number;
    limit?: number;
}

export interface PersonPickerPage {
    results: PersonSelection[];
    total: number;
    page: number;
    limit: number;
}


/** A person without a display name is still identifiable by its type and id. */
export function personDisplayLabel(selection: PersonSelection): string {
    return selection.label?.trim() || `${selection.type_label} #${selection.object_id}`;
}


/** The ids a stored person value holds, whatever its shape. */
export function personValueIds(value: unknown): number[] {
    const values = Array.isArray(value) ? value : [value];

    return values.filter((id): id is number => Number.isInteger(id));
}
