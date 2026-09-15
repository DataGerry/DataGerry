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
import { MultiDataSectionEntry, MultiDataSectionFieldValue, MultiDataSectionSet } from '../../models/cmdb-object';
import { buildObjectPatchPayload, ObjectPatchDiffInput } from './object-patch.util';

/* ------------------------------------------------------------------------------------------------------------------ */

/** Convenience builders keep the scenarios readable. */
const field = (name: string, value: any): MultiDataSectionFieldValue => ({ name, value });
const row = (multi_data_id: number, data: MultiDataSectionFieldValue[]): MultiDataSectionSet => ({ multi_data_id, data });
const section = (section_id: string, values: MultiDataSectionSet[], highest_id = 0): MultiDataSectionEntry =>
    ({ section_id, highest_id, values });

/** Runs the diff with empty defaults so each test only sets what it cares about. */
const diff = (input: Partial<ObjectPatchDiffInput>) => buildObjectPatchPayload({
    originalFields: [],
    editedFields: [],
    originalSections: [],
    editedSections: [],
    ...input
});

/* ------------------------------------------------------------------------------------------------------------------ */

describe('buildObjectPatchPayload', () => {

    /* --------------------------------------------------- FIELDS --------------------------------------------------- */

    describe('field diffing', () => {
        it('omits the fields key when nothing changed', () => {
            const { payload, hasChanges } = diff({
                originalFields: [field('hostname', 'host-1')],
                editedFields: [field('hostname', 'host-1')]
            });

            expect(payload.fields).toBeUndefined();
            expect(hasChanges).toBeFalse();
        });

        it('includes a single changed field', () => {
            const { payload } = diff({
                originalFields: [field('hostname', 'host-1')],
                editedFields: [field('hostname', 'host-2')]
            });

            expect(payload.fields).toEqual([field('hostname', 'host-2')]);
        });

        it('includes only the changed fields among many', () => {
            const { payload } = diff({
                originalFields: [field('a', '1'), field('b', '2'), field('c', '3')],
                editedFields: [field('a', '1'), field('b', 'CHANGED'), field('c', '3')]
            });

            expect(payload.fields).toEqual([field('b', 'CHANGED')]);
        });

        it('includes a field name that is absent from the original', () => {
            const { payload } = diff({
                originalFields: [field('a', '1')],
                editedFields: [field('a', '1'), field('new_field', 'x')]
            });

            expect(payload.fields).toEqual([field('new_field', 'x')]);
        });

        it('includes a field cleared from a value to empty string', () => {
            const { payload } = diff({
                originalFields: [field('note', 'something')],
                editedFields: [field('note', '')]
            });

            expect(payload.fields).toEqual([field('note', '')]);
        });

        it('treats null and empty string as the same (no change)', () => {
            const { payload, hasChanges } = diff({
                originalFields: [field('note', null)],
                editedFields: [field('note', '')]
            });

            expect(payload.fields).toBeUndefined();
            expect(hasChanges).toBeFalse();
        });

        it('treats undefined and empty string as the same (no change)', () => {
            const { payload } = diff({
                originalFields: [field('note', undefined)],
                editedFields: [field('note', '')]
            });

            expect(payload.fields).toBeUndefined();
        });

        it('treats empty string and null as the same (no change)', () => {
            const { payload } = diff({
                originalFields: [field('note', '')],
                editedFields: [field('note', null)]
            });

            expect(payload.fields).toBeUndefined();
        });

        it('includes a numeric change', () => {
            const { payload } = diff({
                originalFields: [field('count', 5)],
                editedFields: [field('count', 10)]
            });

            expect(payload.fields).toEqual([field('count', 10)]);
        });

        it('omits an identical numeric value', () => {
            const { payload } = diff({
                originalFields: [field('count', 5)],
                editedFields: [field('count', 5)]
            });

            expect(payload.fields).toBeUndefined();
        });

        it('conservatively treats a number and its string form as changed', () => {
            // 5 vs "5": cannot be proven equal, so it is sent (backend re-diffs; harmless).
            const { payload } = diff({
                originalFields: [field('count', 5)],
                editedFields: [field('count', '5')]
            });

            expect(payload.fields).toEqual([field('count', '5')]);
        });

        it('includes a boolean change and omits an identical boolean', () => {
            expect(diff({
                originalFields: [field('flag', true)],
                editedFields: [field('flag', false)]
            }).payload.fields).toEqual([field('flag', false)]);

            expect(diff({
                originalFields: [field('flag', true)],
                editedFields: [field('flag', true)]
            }).payload.fields).toBeUndefined();
        });

        it('includes a changed multi-select array and omits an identical one', () => {
            expect(diff({
                originalFields: [field('tags', ['a'])],
                editedFields: [field('tags', ['a', 'b'])]
            }).payload.fields).toEqual([field('tags', ['a', 'b'])]);

            expect(diff({
                originalFields: [field('tags', ['a', 'b'])],
                editedFields: [field('tags', ['a', 'b'])]
            }).payload.fields).toBeUndefined();
        });

        it('conservatively treats a reordered array as changed', () => {
            const { payload } = diff({
                originalFields: [field('tags', ['a', 'b'])],
                editedFields: [field('tags', ['b', 'a'])]
            });

            expect(payload.fields).toEqual([field('tags', ['b', 'a'])]);
        });

        it('omits an identical structured (date-like) value', () => {
            const { payload } = diff({
                originalFields: [field('due', { $date: 1000 })],
                editedFields: [field('due', { $date: 1000 })]
            });

            expect(payload.fields).toBeUndefined();
        });

        it('includes a changed structured (date-like) value', () => {
            const { payload } = diff({
                originalFields: [field('due', { $date: 1000 })],
                editedFields: [field('due', { $date: 2000 })]
            });

            expect(payload.fields).toEqual([field('due', { $date: 2000 })]);
        });

        it('treats a real 0 as a change from empty (0 is not "empty")', () => {
            const { payload } = diff({
                originalFields: [field('count', '')],
                editedFields: [field('count', 0)]
            });

            expect(payload.fields).toEqual([field('count', 0)]);
        });

        it('treats false as a change from empty (false is not "empty")', () => {
            const { payload } = diff({
                originalFields: [field('flag', '')],
                editedFields: [field('flag', false)]
            });

            expect(payload.fields).toEqual([field('flag', false)]);
        });
    });

    /* ----------------------------------------------- CREATED ROWS ------------------------------------------------ */

    describe('created multi_data_section rows', () => {
        it('reports a new row in an existing section and strips its multi_data_id', () => {
            const { payload } = diff({
                originalSections: [section('net', [row(1, [field('ip', '10.0.0.1')])])],
                editedSections: [section('net', [
                    row(1, [field('ip', '10.0.0.1')]),
                    row(2, [field('ip', '10.0.0.2')])
                ])]
            });

            expect(payload.created_mds_rows).toEqual([{ section_id: 'net', data: [field('ip', '10.0.0.2')] }]);
            expect(payload.edited_mds_rows).toBeUndefined();
            expect(payload.deleted_mds_rows).toBeUndefined();
        });

        it('reports a new row when the section had no rows originally', () => {
            const { payload } = diff({
                originalSections: [section('net', [])],
                editedSections: [section('net', [row(1, [field('ip', '10.0.0.1')])])]
            });

            expect(payload.created_mds_rows).toEqual([{ section_id: 'net', data: [field('ip', '10.0.0.1')] }]);
        });

        it('reports every row of a brand new section as created', () => {
            const { payload } = diff({
                originalSections: [],
                editedSections: [section('disks', [
                    row(1, [field('mount', '/')]),
                    row(2, [field('mount', '/data')])
                ])]
            });

            expect(payload.created_mds_rows).toEqual([
                { section_id: 'disks', data: [field('mount', '/')] },
                { section_id: 'disks', data: [field('mount', '/data')] }
            ]);
        });
    });

    /* ------------------------------------------------ EDITED ROWS ------------------------------------------------ */

    describe('edited multi_data_section rows', () => {
        it('reports a changed row with its multi_data_id and full data', () => {
            const { payload } = diff({
                originalSections: [section('net', [row(1, [field('ip', '10.0.0.1'), field('mac', 'AA')])])],
                editedSections: [section('net', [row(1, [field('ip', '10.0.0.9'), field('mac', 'AA')])])]
            });

            expect(payload.edited_mds_rows).toEqual([
                { section_id: 'net', multi_data_id: 1, data: [field('ip', '10.0.0.9'), field('mac', 'AA')] }
            ]);
            expect(payload.created_mds_rows).toBeUndefined();
            expect(payload.deleted_mds_rows).toBeUndefined();
        });

        it('does not report an unchanged row', () => {
            const { payload, hasChanges } = diff({
                originalSections: [section('net', [row(1, [field('ip', '10.0.0.1')])])],
                editedSections: [section('net', [row(1, [field('ip', '10.0.0.1')])])]
            });

            expect(payload.edited_mds_rows).toBeUndefined();
            expect(hasChanges).toBeFalse();
        });

        it('is order-independent when comparing row fields', () => {
            const { payload } = diff({
                originalSections: [section('net', [row(1, [field('ip', '10.0.0.1'), field('mac', 'AA')])])],
                editedSections: [section('net', [row(1, [field('mac', 'AA'), field('ip', '10.0.0.1')])])]
            });

            expect(payload.edited_mds_rows).toBeUndefined();
        });

        it('reports a row whose field count changed', () => {
            const { payload } = diff({
                originalSections: [section('net', [row(1, [field('ip', '10.0.0.1')])])],
                editedSections: [section('net', [row(1, [field('ip', '10.0.0.1'), field('mac', 'AA')])])]
            });

            expect(payload.edited_mds_rows).toEqual([
                { section_id: 'net', multi_data_id: 1, data: [field('ip', '10.0.0.1'), field('mac', 'AA')] }
            ]);
        });

        it('treats null-vs-empty inside a row as unchanged', () => {
            const { payload } = diff({
                originalSections: [section('net', [row(1, [field('ip', null)])])],
                editedSections: [section('net', [row(1, [field('ip', '')])])]
            });

            expect(payload.edited_mds_rows).toBeUndefined();
        });
    });

    /* ----------------------------------------------- DELETED ROWS ------------------------------------------------ */

    describe('deleted multi_data_section rows', () => {
        it('reports a removed row by its multi_data_id', () => {
            const { payload } = diff({
                originalSections: [section('net', [
                    row(1, [field('ip', '10.0.0.1')]),
                    row(2, [field('ip', '10.0.0.2')])
                ])],
                editedSections: [section('net', [row(1, [field('ip', '10.0.0.1')])])]
            });

            expect(payload.deleted_mds_rows).toEqual([{ section_id: 'net', multi_data_id: 2 }]);
            expect(payload.created_mds_rows).toBeUndefined();
            expect(payload.edited_mds_rows).toBeUndefined();
        });

        it('reports every row deleted when a section is cleared', () => {
            const { payload } = diff({
                originalSections: [section('net', [row(1, []), row(2, [])])],
                editedSections: [section('net', [])]
            });

            expect(payload.deleted_mds_rows).toEqual([
                { section_id: 'net', multi_data_id: 1 },
                { section_id: 'net', multi_data_id: 2 }
            ]);
        });

        it('preserves rows when a section is entirely absent from the edited state (not loaded)', () => {
            // A section missing from the edited form was never rendered/loaded, so its rows
            // must be preserved rather than deleted. A section the user actually cleared is
            // present with an empty values array (covered by the test above), which still
            // yields deletions.
            const { payload, hasChanges } = diff({
                originalSections: [section('net', [row(1, [])])],
                editedSections: []
            });

            expect(payload.deleted_mds_rows).toBeUndefined();
            expect(hasChanges).toBeFalse();
        });
    });

    /* --------------------------------------------- COMBINED CHANGES ---------------------------------------------- */

    describe('combined multi_data_section changes', () => {
        it('reports create, edit and delete within a single section', () => {
            const { payload } = diff({
                originalSections: [section('net', [
                    row(1, [field('ip', '10.0.0.1')]),
                    row(2, [field('ip', '10.0.0.2')])
                ], 3)],
                editedSections: [section('net', [
                    row(1, [field('ip', '10.0.0.5')]), // edited
                    // row 2 deleted
                    row(3, [field('ip', '10.0.0.9')])  // created
                ], 4)]
            });

            expect(payload.created_mds_rows).toEqual([{ section_id: 'net', data: [field('ip', '10.0.0.9')] }]);
            expect(payload.edited_mds_rows).toEqual([{ section_id: 'net', multi_data_id: 1, data: [field('ip', '10.0.0.5')] }]);
            expect(payload.deleted_mds_rows).toEqual([{ section_id: 'net', multi_data_id: 2 }]);
        });

        it('reports changes spread across multiple sections', () => {
            const { payload } = diff({
                originalSections: [
                    section('net', [row(1, [field('ip', '10.0.0.1')])], 2),
                    section('disks', [row(7, [field('size', 500)])], 8)
                ],
                editedSections: [
                    section('net', [row(2, [field('ip', '10.0.0.9')])], 3),   // 1 deleted, 2 created
                    section('disks', [row(7, [field('size', 1000)])], 8)      // 7 edited
                ]
            });

            expect(payload.created_mds_rows).toEqual([{ section_id: 'net', data: [field('ip', '10.0.0.9')] }]);
            expect(payload.edited_mds_rows).toEqual([{ section_id: 'disks', multi_data_id: 7, data: [field('size', 1000)] }]);
            expect(payload.deleted_mds_rows).toEqual([{ section_id: 'net', multi_data_id: 1 }]);
        });
    });

    /* ------------------------------------------------ HAS CHANGES ------------------------------------------------ */

    describe('hasChanges flag', () => {
        it('is false with an empty payload when nothing changed', () => {
            const { payload, hasChanges } = diff({
                originalFields: [field('a', '1')],
                editedFields: [field('a', '1')],
                originalSections: [section('net', [row(1, [field('ip', '10.0.0.1')])])],
                editedSections: [section('net', [row(1, [field('ip', '10.0.0.1')])])]
            });

            expect(hasChanges).toBeFalse();
            expect(payload).toEqual({});
        });

        it('is true when only a field changed', () => {
            expect(diff({
                originalFields: [field('a', '1')],
                editedFields: [field('a', '2')]
            }).hasChanges).toBeTrue();
        });

        it('is true when only a row was created', () => {
            expect(diff({
                editedSections: [section('net', [row(1, [field('ip', 'x')])])]
            }).hasChanges).toBeTrue();
        });

        it('is true when only a row was edited', () => {
            expect(diff({
                originalSections: [section('net', [row(1, [field('ip', 'x')])])],
                editedSections: [section('net', [row(1, [field('ip', 'y')])])]
            }).hasChanges).toBeTrue();
        });

        it('is true when only a row was deleted', () => {
            expect(diff({
                originalSections: [section('net', [row(1, [field('ip', 'x')])])],
                editedSections: [section('net', [])]
            }).hasChanges).toBeTrue();
        });
    });

    /* -------------------------------------------------- COMMENT -------------------------------------------------- */

    describe('comment handling', () => {
        it('includes the comment when there is a real change', () => {
            const { payload } = diff({
                originalFields: [field('a', '1')],
                editedFields: [field('a', '2')],
                comment: 'updated a'
            });

            expect(payload.comment).toBe('updated a');
        });

        it('drops the comment when nothing changed (backend rejects no-op patches)', () => {
            const { payload, hasChanges } = diff({
                originalFields: [field('a', '1')],
                editedFields: [field('a', '1')],
                comment: 'this should not be sent'
            });

            expect(hasChanges).toBeFalse();
            expect(payload.comment).toBeUndefined();
        });

        it('does not include an empty-string comment', () => {
            const { payload } = diff({
                originalFields: [field('a', '1')],
                editedFields: [field('a', '2')],
                comment: ''
            });

            expect(payload.comment).toBeUndefined();
        });

        it('does not include a whitespace-only comment', () => {
            const { payload } = diff({
                originalFields: [field('a', '1')],
                editedFields: [field('a', '2')],
                comment: '   '
            });

            expect(payload.comment).toBeUndefined();
        });

        it('does not include an undefined comment', () => {
            const { payload } = diff({
                originalFields: [field('a', '1')],
                editedFields: [field('a', '2')],
                comment: undefined
            });

            expect(payload.comment).toBeUndefined();
        });

        it('preserves a meaningful comment verbatim, including surrounding whitespace', () => {
            const { payload } = diff({
                originalFields: [field('a', '1')],
                editedFields: [field('a', '2')],
                comment: '  add prod node  '
            });

            expect(payload.comment).toBe('  add prod node  ');
        });
    });

    /* ------------------------------------------------ ROBUSTNESS ------------------------------------------------- */

    describe('robustness with missing/empty inputs', () => {
        it('treats undefined field arrays as empty', () => {
            const { payload, hasChanges } = buildObjectPatchPayload({
                originalFields: undefined as any,
                editedFields: undefined as any,
                originalSections: undefined as any,
                editedSections: undefined as any
            });

            expect(payload).toEqual({});
            expect(hasChanges).toBeFalse();
        });

        it('treats an edited field with no original counterpart as new', () => {
            const { payload } = buildObjectPatchPayload({
                originalFields: undefined as any,
                editedFields: [field('a', 'x')],
                originalSections: undefined as any,
                editedSections: undefined as any
            });

            expect(payload.fields).toEqual([field('a', 'x')]);
        });

        it('tolerates a section whose values array is missing', () => {
            const { payload, hasChanges } = diff({
                originalSections: [{ section_id: 'net', highest_id: 0, values: undefined as any }],
                editedSections: [{ section_id: 'net', highest_id: 0, values: undefined as any }]
            });

            expect(payload).toEqual({});
            expect(hasChanges).toBeFalse();
        });
    });

    /* --------------------------------------------- FULL SCENARIO ------------------------------------------------- */

    describe('full edit scenario', () => {
        it('builds the complete partial payload for a realistic edit', () => {
            const { payload, hasChanges } = buildObjectPatchPayload({
                originalFields: [
                    field('hostname', 'old-host'),
                    field('environment', 'staging'),
                    field('os', 'linux'),   // unchanged
                    field('note', null)     // null -> '' below, unchanged
                ],
                editedFields: [
                    field('hostname', 'web-prod-01'),
                    field('environment', 'production'),
                    field('os', 'linux'),
                    field('note', '')
                ],
                originalSections: [
                    section('network-interfaces', [
                        row(1, [field('ip_address', '10.0.0.1'), field('mac', 'AA:00')]),
                        row(2, [field('ip_address', '10.0.0.2'), field('mac', 'AA:02')])
                    ], 3),
                    section('attached-disks', [
                        row(7, [field('mount', '/'), field('size_gb', 500)]),
                        row(8, [field('mount', '/tmp'), field('size_gb', 250)])
                    ], 9)
                ],
                editedSections: [
                    section('network-interfaces', [
                        row(1, [field('ip_address', '10.0.0.5'), field('mac', 'AA:00')]),          // edited
                        row(3, [field('ip_address', '10.0.0.9'), field('mac', 'AA:BB:CC:DD:EE:09')]) // created
                    ], 4),
                    section('attached-disks', [
                        row(7, [field('mount', '/'), field('size_gb', 1000)]),                     // edited
                        row(9, [field('mount', '/data'), field('size_gb', 500)])                   // created
                    ], 10)
                ],
                comment: 'add prod node'
            });

            expect(hasChanges).toBeTrue();
            expect(payload).toEqual({
                fields: [
                    field('hostname', 'web-prod-01'),
                    field('environment', 'production')
                ],
                created_mds_rows: [
                    { section_id: 'network-interfaces', data: [field('ip_address', '10.0.0.9'), field('mac', 'AA:BB:CC:DD:EE:09')] },
                    { section_id: 'attached-disks', data: [field('mount', '/data'), field('size_gb', 500)] }
                ],
                edited_mds_rows: [
                    { section_id: 'network-interfaces', multi_data_id: 1, data: [field('ip_address', '10.0.0.5'), field('mac', 'AA:00')] },
                    { section_id: 'attached-disks', multi_data_id: 7, data: [field('mount', '/'), field('size_gb', 1000)] }
                ],
                deleted_mds_rows: [
                    { section_id: 'network-interfaces', multi_data_id: 2 },
                    { section_id: 'attached-disks', multi_data_id: 8 }
                ],
                comment: 'add prod node'
            });
        });
    });
});
