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
import { CmdbType } from '../../../models/cmdb-type';
import { withPortsFlagOnly } from './ports-type-payload.util';
/* ------------------------------------------------------------------------------------------------------------------ */

const PORTS_TEMPLATE = 'dg-virtual-tpl-ports';

/** Builds a type whose canvas carries the ports section at `portsIndex`, or none at all for -1. */
function typeWithPortsAt(portsIndex: number, overrides: Partial<CmdbType> = {}): CmdbType {
    const sections: Array<any> = [
        { name: 'section_a', label: 'A', type: 'section', fields: ['field_a'] },
        { name: 'section_b', label: 'B', type: 'section', fields: ['field_b'] }
    ];

    if (portsIndex >= 0) {
        sections.splice(portsIndex, 0, {
            name: PORTS_TEMPLATE, label: 'Ports', type: 'section', fields: ['port_field']
        });
    }

    return {
        uses_ports: true,
        fields: [
            { name: 'field_a', type: 'text' },
            { name: 'field_b', type: 'text' },
            { name: 'port_field', type: 'text' }
        ],
        global_template_ids: [PORTS_TEMPLATE],
        render_meta: { icon: '', sections, externals: [], summary: { fields: [] } },
        ...overrides
    } as CmdbType;
}


describe('withPortsFlagOnly', () => {

    it('stores the canvas slot of the ports section', () => {
        const payload = withPortsFlagOnly(typeWithPortsAt(1));

        expect(payload.port_section_index).toBe(1);
        expect(payload.render_meta.sections.map(section => section.name)).toEqual(['section_a', 'section_b']);
    });


    it('stores 0 when the ports section sits first', () => {
        expect(withPortsFlagOnly(typeWithPortsAt(0)).port_section_index).toBe(0);
    });


    it('stores the last slot when the ports section sits last', () => {
        expect(withPortsFlagOnly(typeWithPortsAt(2)).port_section_index).toBe(2);
    });


    it('keeps the stored slot when the canvas never received the ports section', () => {
        const payload = withPortsFlagOnly(typeWithPortsAt(-1, { port_section_index: 2 }));

        expect(payload.uses_ports).toBe(true);
        expect(payload.port_section_index).toBe(2);
    });


    it('falls back to 0 when neither the canvas nor the type carries a slot', () => {
        expect(withPortsFlagOnly(typeWithPortsAt(-1)).port_section_index).toBe(0);
    });


    it('resets the slot for a type that does not use ports', () => {
        const payload = withPortsFlagOnly(typeWithPortsAt(-1, { uses_ports: false, port_section_index: 3 }));

        expect(payload.uses_ports).toBe(false);
        expect(payload.port_section_index).toBe(0);
    });


    it('still strips the section, its fields and its template reference', () => {
        const payload = withPortsFlagOnly(typeWithPortsAt(1));

        expect(payload.fields.map(field => field.name)).toEqual(['field_a', 'field_b']);
        expect(payload.global_template_ids).toEqual([]);
    });
});
