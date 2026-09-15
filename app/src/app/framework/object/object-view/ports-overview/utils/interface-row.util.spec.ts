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
import { MultiDataSectionSet } from 'src/app/framework/models/cmdb-object';
import { IPAM_INTERFACE_FIELD_NAMES } from 'src/app/framework/render/special-types/ipam-interface/models/interface-fields';
import {
    AssignableInterface,
    IPAM_INTERFACE_SECTION_ID,
    InterfaceRelationType,
    PortInterfaceLink
} from '../models/interface-link.types';
import {
    interfaceRowFromAssignable,
    interfaceRowFromLink,
    summarisePortInterfaces,
    toInterfaceLinkView
} from './interface-row.util';
/* ------------------------------------------------------------------------------------------------------------------ */

function row(values: Record<string, unknown>): MultiDataSectionSet {
    return {
        multi_data_id: 2,
        data: Object.keys(values).map((name) => ({ name, value: values[name] }))
    };
}

function link(overrides: Partial<PortInterfaceLink> = {}): PortInterfaceLink {
    return {
        public_id: 41,
        port_id: 9980,
        interface_object_id: 9971,
        interface_section_id: IPAM_INTERFACE_SECTION_ID,
        interface_multi_data_id: 2,
        relation_type: InterfaceRelationType.PHYSICAL,
        author_id: 1,
        creation_time: null,
        last_edit_time: null,
        interface_row: row({
            [IPAM_INTERFACE_FIELD_NAMES.IP_ADDRESS]: '10.0.0.1',
            [IPAM_INTERFACE_FIELD_NAMES.MAC_ADDRESS]: '00:1A:2B:3C:4D:5F'
        }),
        ...overrides
    };
}

function assignable(overrides: Partial<AssignableInterface> = {}): AssignableInterface {
    return {
        interface_object_id: 9971,
        interface_section_id: IPAM_INTERFACE_SECTION_ID,
        interface_multi_data_id: 2,
        subnet: { public_id: 9972, name: 'Office LAN' },
        object_info: { public_id: 9971, type_id: 9961, type_label: 'Server', summary_line: 'Server #9971 - host-9971' },
        active: null,
        ip: '10.0.0.2',
        mac: '00:1A:2B:3C:4D:5F',
        hostname: null,
        domain: null,
        address_family: null,
        ...overrides
    };
}


describe('interfaceRowFromLink', () => {

    it('reads the addresses out of the MDS row', () => {
        const view = interfaceRowFromLink(link());

        expect(view.ip).toBe('10.0.0.1');
        expect(view.mac).toBe('00:1A:2B:3C:4D:5F');
    });


    it('reports a dangling link as null, because the row key is absent rather than null', () => {
        const dangling = link();
        delete dangling.interface_row;

        expect(interfaceRowFromLink(dangling)).toBeNull();
    });


    it('treats an empty field value as not set', () => {
        const view = interfaceRowFromLink(link({
            interface_row: row({ [IPAM_INTERFACE_FIELD_NAMES.IP_ADDRESS]: '   ' })
        }));

        expect(view.ip).toBeNull();
    });
});


describe('the label ladder', () => {

    it('prefers the host name, qualified by its domain', () => {
        const view = interfaceRowFromLink(link({
            interface_row: row({
                [IPAM_INTERFACE_FIELD_NAMES.HOST]: 'srv01',
                [IPAM_INTERFACE_FIELD_NAMES.DOMAIN]: 'corp.local',
                [IPAM_INTERFACE_FIELD_NAMES.IP_ADDRESS]: '10.0.0.1'
            })
        }));

        expect(view.label).toBe('srv01.corp.local');
    });


    it('falls back to the address, and then to the MAC', () => {
        expect(interfaceRowFromAssignable(assignable({ hostname: null })).label).toBe('10.0.0.2');
        expect(interfaceRowFromAssignable(assignable({ hostname: null, ip: null })).label).toBe('00:1A:2B:3C:4D:5F');
    });


    it('names the row itself when it carries no address at all', () => {
        const view = interfaceRowFromAssignable(assignable({ hostname: null, ip: null, mac: null }));

        expect(view.label).toBe('Row #2');
    });


    it('leaves out of the details whatever the label already says', () => {
        const view = interfaceRowFromAssignable(assignable({ hostname: null, mac: null }));

        expect(view.label).toBe('10.0.0.2');
        expect(view.details).toBe('Office LAN');
    });
});


describe('interfaceRowFromAssignable', () => {

    it('names the object by its summary line', () => {
        expect(interfaceRowFromAssignable(assignable()).objectLabel).toBe('Server #9971 - host-9971');
    });


    it('falls back to the id when the read carried no summary', () => {
        const view = interfaceRowFromAssignable(assignable({ object_info: null }));

        expect(view.objectLabel).toBe('Object #9971');
    });
});


describe('toInterfaceLinkView', () => {

    it('keeps the row reference, which a relation-type update has to send back unchanged', () => {
        const view = toInterfaceLinkView(link());

        expect(view.reference).toEqual({
            interface_object_id: 9971,
            interface_section_id: IPAM_INTERFACE_SECTION_ID,
            interface_multi_data_id: 2
        });
        expect(view.relationLabel).toBe('Physical');
    });
});


describe('summarisePortInterfaces', () => {

    it('reports nothing for a port without links', () => {
        expect(summarisePortInterfaces([])).toEqual({ label: null, address: null, additional: 0, dangling: 0 });
    });


    it('counts the links beyond the first one', () => {
        const summary = summarisePortInterfaces([link(), link({ public_id: 42 }), link({ public_id: 43 })]);

        expect(summary.label).toBe('10.0.0.1');
        expect(summary.additional).toBe(2);
    });


    it('shows the address beside the label only when the label is a host name', () => {
        const named = link({
            interface_row: row({
                [IPAM_INTERFACE_FIELD_NAMES.HOST]: 'srv01',
                [IPAM_INTERFACE_FIELD_NAMES.IP_ADDRESS]: '10.0.0.1'
            })
        });

        expect(summarisePortInterfaces([named]).address).toBe('10.0.0.1');
        expect(summarisePortInterfaces([link()]).address).toBeNull();
    });


    it('keeps a label when only some of the links are dangling', () => {
        const dangling = link({ public_id: 42 });
        delete dangling.interface_row;

        const summary = summarisePortInterfaces([link(), dangling]);

        expect(summary.label).toBe('10.0.0.1');
        expect(summary.dangling).toBe(1);
    });


    it('reports no label when every link of the port is dangling', () => {
        const dangling = link();
        delete dangling.interface_row;

        expect(summarisePortInterfaces([dangling]).label).toBeNull();
    });
});
