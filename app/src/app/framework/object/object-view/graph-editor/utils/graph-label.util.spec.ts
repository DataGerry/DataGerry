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

* You should have received a copy of the GNU Affero General Public License
* along with this program. If not, see <https://www.gnu.org/licenses/>.
*/
import { CmdbType } from 'src/app/framework/models/cmdb-type';

import { ciNode, linkedObject } from '../testing/graph-fixtures';
import { labelFieldOptions, titleForLabelField } from './graph-label.util';

function type(overrides: Partial<CmdbType> = {}): CmdbType {
    return {
        fields: [],
        render_meta: { icon: '', sections: [], externals: [], summary: { fields: [] } },
        ...overrides
    } as CmdbType;
}

describe('labelFieldOptions', () => {
    it('leaves out the fields that live in a multi-data section', () => {
        const options = labelFieldOptions(type({
            fields: [
                { name: 'name', label: 'Name', type: 'text' },
                { name: 'port', label: 'Port', type: 'text' }
            ],
            render_meta: {
                icon: '',
                externals: [],
                summary: { fields: [] },
                sections: [
                    { type: 'section', name: 's1', label: 'General', fields: ['name'] },
                    { type: 'multi-data-section', name: 's2', label: 'Ports', fields: ['port'] }
                ]
            }
        }));

        expect(options.map(option => option.name)).toEqual(['name']);
    });

    it('accepts a section that lists its fields as objects', () => {
        const options = labelFieldOptions(type({
            fields: [{ name: 'name', label: 'Name', type: 'text' }],
            render_meta: {
                icon: '',
                externals: [],
                summary: { fields: [] },
                sections: [{ type: 'section', name: 's1', label: 'General', fields: [{ name: 'name' }] }]
            }
        }));

        expect(options.map(option => option.name)).toEqual(['name']);
    });

    /** A type may carry two fields with the same label, which the picker has to tell apart. */
    it('appends the field name when two fields share a label', () => {
        const options = labelFieldOptions(type({
            fields: [
                { name: 'location', label: 'Location', type: 'text' },
                { name: 'location_ref', label: 'Location', type: 'ref' },
                { name: 'name', label: 'Name', type: 'text' }
            ],
            render_meta: {
                icon: '',
                externals: [],
                summary: { fields: [] },
                sections: [{
                    type: 'section',
                    name: 's1',
                    label: 'General',
                    fields: ['location', 'location_ref', 'name']
                }]
            }
        }));

        expect(options.map(option => option.display))
            .toEqual(['Location (location)', 'Location (location_ref)', 'Name']);
    });

    it('returns nothing for a type that was never loaded', () => {
        expect(labelFieldOptions(null)).toEqual([]);
    });
});


describe('titleForLabelField', () => {
    const node = ciNode(1, 0, {
        linked_object: linkedObject({ public_id: 1, fields: [{ name: 'city', value: 'Bremen' }] })
    });

    it('reads the value of the named field', () => {
        expect(titleForLabelField(node, 'city')).toBe('Bremen');
    });

    it('reports no field as unset, which the canvas words as "Label not selected"', () => {
        expect(titleForLabelField(node, null)).toBeNull();
    });

    it('reports a field the object does not carry as empty', () => {
        expect(titleForLabelField(node, 'street')).toBe('');
    });
});
