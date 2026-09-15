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
* along with this program.  If not, see <https://www.gnu.org/licenses/>.
*/
import {
    MultiDataSectionEntry,
    MultiDataSectionFieldValue,
    ObjectPatchPayload
} from '../../models/cmdb-object';
/* ------------------------------------------------------------------------------------------------------------------ */

export interface ObjectPatchDiffInput {
    /** Object fields as loaded from the backend before editing. */
    originalFields: MultiDataSectionFieldValue[];
    /** Object fields as they currently stand in the edit form. */
    editedFields: MultiDataSectionFieldValue[];
    /** Multi_data_sections as loaded from the backend before editing. */
    originalSections: MultiDataSectionEntry[];
    /** Multi_data_sections as they currently stand in the edit form. */
    editedSections: MultiDataSectionEntry[];
    /** Optional commit comment for the edit log. */
    comment?: string;
}


export interface ObjectPatchDiffResult {
    payload: ObjectPatchPayload;
    /** True when the payload carries at least one field or MDS row change. */
    hasChanges: boolean;
}

/* ------------------------------------------------------------------------------------------------------------------ */

/**
 * Builds the partial payload for the object PATCH route by diffing the edited form state
 * against the state loaded from the backend.
 *
 * The field diff is intentionally conservative: a field is only skipped when it is provably
 * unchanged. When two values cannot be compared reliably the field is included, so a real
 * change is never dropped (an unchanged field that slips through is harmless — the backend
 * re-merges it and computes its own version diff).
 */
export function buildObjectPatchPayload(input: ObjectPatchDiffInput): ObjectPatchDiffResult {
    const payload: ObjectPatchPayload = {};

    const fields = diffFields(input.originalFields ?? [], input.editedFields ?? []);
    const { created, edited, deleted } = diffSections(input.originalSections ?? [], input.editedSections ?? []);

    if (fields.length) {
        payload.fields = fields;
    }
    if (created.length) {
        payload.created_mds_rows = created;
    }
    if (edited.length) {
        payload.edited_mds_rows = edited;
    }
    if (deleted.length) {
        payload.deleted_mds_rows = deleted;
    }

    const hasChanges = Object.keys(payload).length > 0;

    // The backend rejects a patch that changes nothing, so the comment only rides along
    // with an actual change.
    if (hasChanges && typeof input.comment === 'string' && input.comment.trim() !== '') {
        payload.comment = input.comment;
    }

    return { payload, hasChanges };
}

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

/**
 * Returns the fields whose value changed compared to the original snapshot,
 * plus any field name not present in the original.
 */
function diffFields(
    original: MultiDataSectionFieldValue[],
    edited: MultiDataSectionFieldValue[]
): MultiDataSectionFieldValue[] {
    const originalByName = new Map(original.map((field) => [field.name, field.value]));

    return edited.filter((field) =>
        !originalByName.has(field.name) || !valuesEqual(originalByName.get(field.name), field.value)
    );
}


/**
 * Diffs the multi_data_section rows per section using the multi_data_id as the row identity.
 * New rows drop their id (the backend assigns it), changed rows keep it, and rows that
 * disappeared are reported as deletions.
 */
function diffSections(original: MultiDataSectionEntry[], edited: MultiDataSectionEntry[]) {
    const created: ObjectPatchPayload['created_mds_rows'] = [];
    const editedRows: ObjectPatchPayload['edited_mds_rows'] = [];
    const deleted: ObjectPatchPayload['deleted_mds_rows'] = [];

    const originalBySection = new Map(original.map((section) => [section.section_id, section]));
    const editedBySection = new Map(edited.map((section) => [section.section_id, section]));

    for (const section of edited) {
        const originalRows = new Map(
            (originalBySection.get(section.section_id)?.values ?? []).map((row) => [row.multi_data_id, row])
        );

        for (const row of section.values ?? []) {
            const originalRow = originalRows.get(row.multi_data_id);

            if (!originalRow) {
                created.push({ section_id: section.section_id, data: row.data });
            } else if (!rowsEqual(originalRow.data, row.data)) {
                editedRows.push({ section_id: section.section_id, multi_data_id: row.multi_data_id, data: row.data });
            }
        }
    }

    for (const section of original) {
        const editedSection = editedBySection.get(section.section_id);

        // A section missing entirely from the edited state was never loaded into the form
        // (e.g. its control had not been registered yet). Leave its rows untouched instead of
        // deleting them. A section the user actually cleared is still present here with an
        // empty values array, so genuine row removals are still detected below.
        if (!editedSection) {
            continue;
        }

        const editedIds = new Set((editedSection.values ?? []).map((row) => row.multi_data_id));

        for (const row of section.values ?? []) {
            if (!editedIds.has(row.multi_data_id)) {
                deleted.push({ section_id: section.section_id, multi_data_id: row.multi_data_id });
            }
        }
    }

    return { created, edited: editedRows, deleted };
}


/**
 * Compares two MDS row data arrays by field name. Order-independent and biased towards
 * reporting a difference so a real edit is never missed.
 */
function rowsEqual(original: MultiDataSectionFieldValue[], edited: MultiDataSectionFieldValue[]): boolean {
    if ((original?.length ?? 0) !== (edited?.length ?? 0)) {
        return false;
    }

    const originalByName = new Map((original ?? []).map((field) => [field.name, field.value]));

    return (edited ?? []).every((field) =>
        originalByName.has(field.name) && valuesEqual(originalByName.get(field.name), field.value)
    );
}


/**
 * Conservative value equality. Treats null/undefined/empty-string as the same "empty" value,
 * compares primitives strictly, and falls back to a structural JSON comparison. Anything that
 * cannot be matched confidently is treated as different.
 */
function valuesEqual(a: unknown, b: unknown): boolean {
    const normalizedA = normalizeEmpty(a);
    const normalizedB = normalizeEmpty(b);

    if (normalizedA === normalizedB) {
        return true;
    }

    if (normalizedA === '' || normalizedB === '' ||
        typeof normalizedA !== 'object' || typeof normalizedB !== 'object') {
        return false;
    }

    try {
        return JSON.stringify(normalizedA) === JSON.stringify(normalizedB);
    } catch {
        return false;
    }
}


function normalizeEmpty(value: unknown): unknown {
    return value === null || value === undefined || value === '' ? '' : value;
}
