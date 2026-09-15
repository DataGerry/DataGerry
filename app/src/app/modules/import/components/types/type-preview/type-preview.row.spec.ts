import { ImportTypeEntry } from '../../../models/import-type.models';
import { buildTypePreviewRows, filterTypePreviewRows } from './type-preview.row';

/**
 * The preview rows are built from an uploaded file, so nothing in them can be trusted. These tests
 * cover the fallbacks for missing data and the icon whitelist that keeps the upload out of the DOM.
 */
describe('type preview rows (type import - review step data)', () => {

    describe('buildTypePreviewRows', () => {
        it('flattens a complete entry into one row', () => {
            const types: ImportTypeEntry[] = [{
                public_id: 7,
                name: 'server',
                label: 'Server',
                fields: [{ name: 'hostname' }, { name: 'serial' }],
                render_meta: { icon: 'fas fa-server', sections: [{ name: 'general' }] }
            }];

            expect(buildTypePreviewRows(types)).toEqual([{
                index: 0,
                label: 'Server',
                name: 'server',
                publicId: 7,
                icon: 'fas fa-server',
                fieldCount: 2,
                sectionCount: 1,
                searchTerm: 'server server'
            }]);
        });

        it('keeps the position in the upload, so a removal hits the right entry', () => {
            const rows = buildTypePreviewRows([{ name: 'a' }, { name: 'b' }, { name: 'c' }]);

            expect(rows.map((row) => row.index)).toEqual([0, 1, 2]);
        });

        it('falls back to the technical name when a type has no label', () => {
            expect(buildTypePreviewRows([{ name: 'server' }])[0].label).toBe('server');
        });

        it('falls back to a placeholder when a type has neither label nor name', () => {
            const row = buildTypePreviewRows([{}])[0];

            expect(row.label).toBe('Unnamed type');
            expect(row.name).toBe('—');
        });

        it('shows no public id for a new type or a non numeric one', () => {
            expect(buildTypePreviewRows([{ name: 'server' }])[0].publicId).toBeNull();
            expect(buildTypePreviewRows([{ name: 'server', public_id: '7' as any }])[0].publicId).toBeNull();
        });

        it('counts zero fields and sections when the upload carries none', () => {
            const row = buildTypePreviewRows([{ name: 'server' }])[0];

            expect(row.fieldCount).toBe(0);
            expect(row.sectionCount).toBe(0);
        });

        it('makes label and name searchable in lower case', () => {
            expect(buildTypePreviewRows([{ name: 'web_server', label: 'Web Server' }])[0].searchTerm)
                .toBe('web server web_server');
        });

        it('builds nothing for an empty or missing upload', () => {
            expect(buildTypePreviewRows([])).toEqual([]);
            expect(buildTypePreviewRows(null)).toEqual([]);
            expect(buildTypePreviewRows(undefined)).toEqual([]);
        });

        describe('icon handling', () => {
            it('keeps a plain icon class from the upload', () => {
                expect(buildTypePreviewRows([{ name: 'a', render_meta: { icon: 'fas fa-cube' } }])[0].icon)
                    .toBe('fas fa-cube');
            });

            it('falls back to the default icon when the upload carries none', () => {
                expect(buildTypePreviewRows([{ name: 'a' }])[0].icon).toBe('fas fa-cube');
                expect(buildTypePreviewRows([{ name: 'a', render_meta: { icon: '' } }])[0].icon).toBe('fas fa-cube');
            });

            it('refuses an icon value that is not a plain class token', () => {
                const malicious = '"><img src=x onerror=alert(1)>';

                expect(buildTypePreviewRows([{ name: 'a', render_meta: { icon: malicious } }])[0].icon).toBe('fas fa-cube');
            });

            it('refuses icon values carrying quotes, angle brackets or a colon', () => {
                ['fa"cube', 'fa<cube', "fa'cube", 'javascript:alert(1)'].forEach((icon) => {
                    expect(buildTypePreviewRows([{ name: 'a', render_meta: { icon } }])[0].icon).toBe('fas fa-cube');
                });
            });
        });
    });

    describe('filterTypePreviewRows', () => {
        const rows = buildTypePreviewRows([
            { name: 'web_server', label: 'Web Server' },
            { name: 'router', label: 'Router' },
            { name: 'switch', label: 'Network Switch' }
        ]);

        it('returns everything for an empty search', () => {
            expect(filterTypePreviewRows(rows, '')).toBe(rows);
            expect(filterTypePreviewRows(rows, '   ')).toBe(rows);
        });

        it('matches the label case insensitively', () => {
            expect(filterTypePreviewRows(rows, 'NETWORK').map((row) => row.name)).toEqual(['switch']);
        });

        it('matches the technical name', () => {
            expect(filterTypePreviewRows(rows, 'web_').map((row) => row.name)).toEqual(['web_server']);
        });

        it('matches a partial term anywhere in the row', () => {
            expect(filterTypePreviewRows(rows, 'er').map((row) => row.name)).toEqual(['web_server', 'router']);
        });

        it('ignores surrounding whitespace of the search term', () => {
            expect(filterTypePreviewRows(rows, '  router  ').map((row) => row.name)).toEqual(['router']);
        });

        it('returns nothing when no row matches', () => {
            expect(filterTypePreviewRows(rows, 'firewall')).toEqual([]);
        });
    });
});
