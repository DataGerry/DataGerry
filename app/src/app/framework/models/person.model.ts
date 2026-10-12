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

/** Field type of the "Person / Person group selector" control. */
export const PERSON_FIELD_TYPE = 'person';

/** The person group's members field: a multiple person field restricted to persons. */
export const PERSON_GROUP_MEMBERS_FIELD = 'dg-person-group-members';

/** What a selection points at - the special type of the referenced object. */
export type PersonRefType = 'PERSON' | 'PERSON_GROUP';

/** What a person field may select, stored under the field's `person_ref_kind` key. */
export enum PersonRefKind {
    PERSON = 'PERSON',
    PERSON_GROUP = 'PERSON_GROUP',
    BOTH = 'BOTH'
}

export const PERSON_REF_KIND_OPTIONS: ReadonlyArray<{ value: PersonRefKind; label: string }> = [
    { value: PersonRefKind.PERSON, label: 'Persons' },
    { value: PersonRefKind.PERSON_GROUP, label: 'Person groups' },
    { value: PersonRefKind.BOTH, label: 'Persons and person groups' }
];

/** One stored selection of a person field. */
export interface PersonSelection {
    ref_type: PersonRefType;
    id: number;
}

/** A single field stores one selection or null, a multiple one a list of them. */
export type PersonFieldValue = PersonSelection | Array<PersonSelection> | null;

/** A selectable person or person group, as GET /person_relations/candidates answers it. */
export interface PersonCandidate extends PersonSelection {
    label: string;
    type_id: number;
}

/** An object pointing at a person or group through one of its person fields. */
export interface PersonAssignment {
    object_id: number;
    type_id: number;
    type_label: string;
    label: string;
    field_name: string;
    field_label: string;
}

/** GET /person_relations/<object_id>. */
export interface PersonRelations {
    ref_type: PersonRefType;
    /** The groups of a person; empty for a group. */
    memberships: Array<PersonCandidate>;
    /** The persons of a group; empty for a person. */
    members: Array<PersonCandidate>;
    assignments: Array<PersonAssignment>;
}

/** GET /person_relations/types: the CmdbType carrying each person special type, or null. */
export interface PersonRelationTypes {
    PERSON: number | null;
    PERSON_GROUP: number | null;
}


/** Normalizes whatever a field holds ('' / null / one pair / a list) into a list of selections. */
export function personSelectionsOf(value: unknown): Array<PersonSelection> {
    if (value === null || value === undefined || value === '') {
        return [];
    }

    const entries = Array.isArray(value) ? value : [value];

    return entries.filter((entry): entry is PersonSelection =>
        !!entry && typeof entry === 'object' && 'id' in entry && 'ref_type' in entry
    );
}


/** The key a selection is matched by - an id alone is unique, the ref type keeps it readable. */
export function personSelectionKey(selection: PersonSelection | null | undefined): string {
    return selection ? `${ selection.ref_type }:${ selection.id }` : '';
}
