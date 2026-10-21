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
import { MultiDataSectionEntry, MultiDataSectionSet } from '../../../models/cmdb-object';
import { getNextMultiDataId } from './mds-id.util';

/* ------------------------------------------------------------------------------------------------------------------ */

const row = (multi_data_id: number): MultiDataSectionSet => ({ multi_data_id, data: [] });
const section = (highest_id: number, ids: number[]): MultiDataSectionEntry =>
    ({ section_id: 'net', highest_id, values: ids.map(row) });

/* ------------------------------------------------------------------------------------------------------------------ */

describe('getNextMultiDataId', () => {

    it('returns 1 for a fresh, empty section', () => {
        expect(getNextMultiDataId(section(0, []))).toBe(1);
    });

    it('does NOT reuse the id of a single backend-created row (the reported bug)', () => {
        // Backend assigns highest_id = last id, so a lone row has id 1 and highest_id 1.
        // The new id must be 2, never 1.
        expect(getNextMultiDataId(section(1, [1]))).toBe(2);
    });

    it('returns one past the highest for contiguous rows', () => {
        expect(getNextMultiDataId(section(3, [1, 2, 3]))).toBe(4);
    });

    it('handles legacy 0-indexed rows produced by the old frontend', () => {
        expect(getNextMultiDataId(section(2, [0, 1]))).toBe(3);
    });

    it('never collides when highest_id is stale (lower than the max id present)', () => {
        // Defensive: even if the counter is wrong, the max id present wins.
        expect(getNextMultiDataId(section(1, [1, 5]))).toBe(6);
    });

    it('respects a counter that is higher than every id present', () => {
        expect(getNextMultiDataId(section(10, [1, 2]))).toBe(11);
    });

    it('handles gaps in the id sequence', () => {
        expect(getNextMultiDataId(section(3, [1, 3]))).toBe(4);
    });

    it('does not reuse a gap left by a deletion (uses the counter, not the free slot)', () => {
        // Rows [2] with counter 3 (id 1 was deleted). Next id is 4, not the free 1 or 3.
        expect(getNextMultiDataId(section(3, [2]))).toBe(4);
    });

    it('uses the counter when the section has no rows', () => {
        expect(getNextMultiDataId(section(5, []))).toBe(6);
    });

    it('handles large ids', () => {
        expect(getNextMultiDataId(section(999, [999]))).toBe(1000);
    });

    /* ------------------------------------------------- DEFENSIVE ------------------------------------------------- */

    it('returns 1 for a null section', () => {
        expect(getNextMultiDataId(null)).toBe(1);
    });

    it('returns 1 for an undefined section', () => {
        expect(getNextMultiDataId(undefined)).toBe(1);
    });

    it('falls back to the counter when values is missing', () => {
        expect(getNextMultiDataId({ section_id: 'net', highest_id: 4, values: undefined as any })).toBe(5);
    });

    it('falls back to the row ids when highest_id is missing', () => {
        expect(getNextMultiDataId({ section_id: 'net', highest_id: undefined as any, values: [row(1)] })).toBe(2);
    });

    it('returns 1 when both counter and values are missing', () => {
        expect(getNextMultiDataId({ section_id: 'net', highest_id: undefined as any, values: undefined as any })).toBe(1);
    });

    it('ignores rows with a non-numeric or missing multi_data_id', () => {
        const dirty: MultiDataSectionEntry = {
            section_id: 'net',
            highest_id: 0,
            values: [
                { multi_data_id: undefined as any, data: [] },
                { multi_data_id: 3, data: [] },
                { multi_data_id: NaN as any, data: [] }
            ]
        };
        expect(getNextMultiDataId(dirty)).toBe(4);
    });

    /* ------------------------------------------------- SEQUENCE -------------------------------------------------- */

    it('produces strictly increasing, collision-free ids across a realistic add/delete session', () => {
        // Start from a backend object with one row (id 1, counter 1) and mimic the component:
        // after each add, adopt the new id as the counter.
        const s: MultiDataSectionEntry = section(1, [1]);
        const assigned: number[] = [];

        const add = () => {
            const id = getNextMultiDataId(s);
            s.values.push(row(id));
            s.highest_id = id;
            assigned.push(id);
            return id;
        };
        const remove = (id: number) => {
            s.values = s.values.filter((r) => r.multi_data_id !== id);
        };

        const a = add();          // -> 2
        const b = add();          // -> 3
        remove(b);                // delete the second added row
        const c = add();          // -> 4 (must not reuse 3, must not collide with 1 or 2)

        expect([a, b, c]).toEqual([2, 3, 4]);
        // Every assigned id is unique and never equals the pre-existing id 1.
        expect(new Set(assigned).size).toBe(assigned.length);
        expect(assigned).not.toContain(1);
        // Final section holds distinct ids only.
        const finalIds = s.values.map((r) => r.multi_data_id);
        expect(new Set(finalIds).size).toBe(finalIds.length);
    });
});
