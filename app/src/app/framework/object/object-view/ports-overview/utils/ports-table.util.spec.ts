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
import { IPAM_INTERFACE_FIELD_NAMES } from 'src/app/framework/render/special-types/ipam-interface/models/interface-fields';
import { Sort, SortDirection } from 'src/app/layout/table/table.types';
import {
    IPAM_INTERFACE_SECTION_ID,
    InterfaceRelationType,
    PortInterfaceLink
} from '../models/interface-link.types';
import { PortDeviceKind } from '../models/port-bulk.types';
import { CableSource, ConnectionType, PortConnectionState, ResolvedCable } from '../models/port-connection.types';
import { OverviewPort, PortSide } from '../models/ports-overview.types';
import {
    clampPage,
    overviewPorts,
    pageRows,
    portsOfPanelRows,
    sortPatchPanelRows,
    sortPortRows,
    toCableConnection,
    toCmdbPort,
    toPatchPanelRows,
    toPortRow,
    toStandardRows
} from './ports-table.util';
/* ------------------------------------------------------------------------------------------------------------------ */

function port(overrides: Partial<OverviewPort> = {}): OverviewPort {
    return {
        port_id: 1,
        side: PortSide.SINGLE,
        port_number: 1,
        name: 'Gi1/0/1',
        description: null,
        connected: false,
        cable: null,
        cable_connection_id: null,
        connected_port: null,
        connected_object: null,
        interface_links: [],
        status: { id: null, label: null },
        port_type: { id: null, label: null },
        speed: { id: null, label: null },
        ...overrides
    };
}

function interfaceLink(overrides: Partial<PortInterfaceLink> = {}): PortInterfaceLink {
    return {
        public_id: 5501,
        port_id: 1,
        interface_object_id: 8802,
        interface_section_id: IPAM_INTERFACE_SECTION_ID,
        interface_multi_data_id: 1,
        relation_type: InterfaceRelationType.PHYSICAL,
        author_id: 1,
        creation_time: null,
        last_edit_time: null,
        interface_row: {
            multi_data_id: 1,
            data: [{ name: IPAM_INTERFACE_FIELD_NAMES.IP_ADDRESS, value: '10.0.0.5' }]
        },
        ...overrides
    };
}

function cable(overrides: Partial<ResolvedCable> = {}): ResolvedCable {
    return {
        source: CableSource.INLINE,
        cable_ci_id: null,
        name: null,
        type: null,
        type_id: null,
        length: null,
        color: null,
        description: null,
        ...overrides
    };
}

/** A port cabled to Gi1/1 of object 9872. */
function cabledPort(overrides: Partial<OverviewPort> = {}): OverviewPort {
    return port({
        port_id: 9880,
        connected: true,
        cable: cable({ name: 'Patch 3m' }),
        cable_connection_id: 9890,
        connected_port: { port_id: 9884, name: 'Gi1/1', side: PortSide.SINGLE },
        connected_object: { object_id: 9872, label: 'host-9872', restricted: false },
        ...overrides
    });
}

const BY_NAME: Sort = { name: 'name', order: SortDirection.ASCENDING };


describe('ports-table.util', () => {

    describe('toPortRow', () => {
        it('reads the labels the overview already resolved', () => {
            const row = toPortRow(port({
                status: { id: 7, label: 'Up' },
                port_type: { id: 10, label: 'RJ45' },
                speed: { id: 25, label: '1G' }
            }));

            expect([row.status, row.portType, row.speed]).toEqual(['Up', 'RJ45', '1G']);
        });

        it('shows nothing for an option without a label, never its id', () => {
            expect(toPortRow(port({ status: { id: 999, label: null } })).status).toBeNull();
        });

        it('reads a port without a cable as free', () => {
            const row = toPortRow(port({ connected: true }));

            expect(row.connectionState).toBe(PortConnectionState.FREE);
            expect(row.connectionLabel).toBe('Free');
            expect(row.farEndLabel).toBeNull();
        });

        it('names the cable and the port and object at its far end', () => {
            const row = toPortRow(cabledPort());

            expect(row.connectionState).toBe(PortConnectionState.CABLED);
            expect(row.connectionLabel).toBe('Patch 3m');
            expect(row.cableConnectionId).toBe(9890);
            expect(row.farEndLabel).toBe('Gi1/1 · host-9872');
        });

        it('does not name a far end the user may not read', () => {
            const row = toPortRow(cabledPort({
                connected_port: { port_id: 9885, name: null, side: null },
                connected_object: { object_id: 9873, label: null, restricted: true }
            }));

            expect(row.farEndLabel).toBe('Restricted object');
        });

        it('summarises the embedded interface links', () => {
            const row = toPortRow(port({ interface_links: [interfaceLink(), interfaceLink({ public_id: 5502 })] }));

            expect(row.interfaceLabel).toBe('10.0.0.5');
            expect(row.interfaces.additionalLabels.length).toBe(1);
        });
    });


    describe('toStandardRows', () => {
        it('builds one row per port', () => {
            const rows = toStandardRows([{ port: port() }, { port: port({ port_id: 2, name: 'Gi1/0/2' }) }]);

            expect(rows.map((row) => row.publicId)).toEqual([1, 2]);
        });
    });


    describe('toPatchPanelRows', () => {
        const front = port({ port_id: 9881, side: PortSide.FRONT, name: 'F01', port_number: 1 });
        const rear = cabledPort({ port_id: 9882, side: PortSide.REAR, name: 'R01', port_number: 1 });
        const lonely = port({ port_id: 9883, side: PortSide.FRONT, name: 'F02', port_number: 2 });

        const rows = toPatchPanelRows([
            { front, rear, paired: true },
            { front: lonely, rear: null, paired: false }
        ]);

        it('builds one row per pairing with both faces side by side', () => {
            expect(rows.length).toBe(2);
            expect(rows[0].front.name).toBe('F01');
            expect(rows[0].rear.name).toBe('R01');
            expect(rows[0].paired).toBeTrue();
        });

        it('keeps an unpaired port on its own row', () => {
            expect(rows[1].key).toBe(9883);
            expect(rows[1].rear).toBeNull();
            expect(rows[1].paired).toBeFalse();
        });

        it('falls back to the rear port when the front one is missing', () => {
            const [row] = toPatchPanelRows([{ front: null, rear, paired: false }]);

            expect(row.key).toBe(9882);
            expect(row.portNumber).toBe(1);
        });

        it('hands both faces of a selected pairing to the bulk actions', () => {
            expect(portsOfPanelRows(rows).map((row) => row.name)).toEqual(['F01', 'R01', 'F02']);
        });

        it('sorts pairings by the rear port name', () => {
            const sorted = sortPatchPanelRows(rows, { name: 'rear', order: SortDirection.ASCENDING });

            expect(sorted.map((row) => row.key)).toEqual([9881, 9883]);
        });
    });


    describe('overviewPorts', () => {
        it('collects the ports of either row shape', () => {
            const standard = overviewPorts({
                device_kind: PortDeviceKind.STANDARD,
                rows: [{ port: port() }],
                total: 1
            });
            const panel = overviewPorts({
                device_kind: PortDeviceKind.PATCH_PANEL,
                rows: [{ front: port({ port_id: 2 }), rear: null, paired: false }],
                total: 1
            });

            expect(standard.map((entry) => entry.port_id)).toEqual([1]);
            expect(panel.map((entry) => entry.port_id)).toEqual([2]);
        });
    });


    describe('toCmdbPort', () => {
        it('keeps the option ids the edit form preselects', () => {
            const stored = toCmdbPort(port({ status: { id: 7, label: 'Up' }, speed: { id: 25, label: '1G' } }), 20);

            expect(stored.object_id).toBe(20);
            expect(stored.status).toBe(7);
            expect(stored.speed).toBe(25);
            expect(stored.port_type).toBeNull();
        });
    });


    describe('toCableConnection', () => {
        it('rebuilds the cable with both endpoints sorted', () => {
            const connection = toCableConnection(cabledPort());

            expect(connection.public_id).toBe(9890);
            expect(connection.endpoints).toEqual([9880, 9884]);
            expect(connection.connection_type).toBe(ConnectionType.CABLE);
            expect(connection.cable.name).toBe('Patch 3m');
        });

        it('is null for a port without a cable', () => {
            expect(toCableConnection(port())).toBeNull();
        });
    });


    describe('sortPortRows', () => {
        const rows = toStandardRows([
            { port: port({ port_id: 1, name: 'Gi1/0/2', port_number: 2, description: 'Uplink' }) },
            { port: port({ port_id: 2, name: 'Gi1/0/10', port_number: 10 }) },
            { port: port({ port_id: 3, name: 'Gi1/0/1', port_number: 1 }) }
        ]);

        it('collates numbered port names naturally', () => {
            const sorted = sortPortRows(rows, BY_NAME);

            expect(sorted.map(row => row.name)).toEqual(['Gi1/0/1', 'Gi1/0/2', 'Gi1/0/10']);
        });

        it('sorts descending on request', () => {
            const sorted = sortPortRows(rows, { name: 'name', order: SortDirection.DESCENDING });

            expect(sorted.map(row => row.name)).toEqual(['Gi1/0/10', 'Gi1/0/2', 'Gi1/0/1']);
        });

        it('sorts port numbers numerically, not as text', () => {
            const sorted = sortPortRows(rows, { name: 'port_number', order: SortDirection.ASCENDING });

            expect(sorted.map(row => row.portNumber)).toEqual([1, 2, 10]);
        });

        it('sorts rows without a value last', () => {
            const sorted = sortPortRows(rows, { name: 'description', order: SortDirection.ASCENDING });

            expect(sorted[0].description).toBe('Uplink');
        });

        it('keeps the backend order for an unsorted column', () => {
            const sorted = sortPortRows(rows, { name: 'unknown', order: SortDirection.ASCENDING });

            expect(sorted.map(row => row.name)).toEqual(['Gi1/0/2', 'Gi1/0/10', 'Gi1/0/1']);
        });

        it('leaves the source list untouched', () => {
            const original = rows.map(row => row.name);

            sortPortRows(rows, BY_NAME);

            expect(rows.map(row => row.name)).toEqual(original);
        });
    });


    describe('paging', () => {
        const rows = toStandardRows(
            Array.from({ length: 12 }, (_, index) => ({ port: port({ port_id: index + 1, port_number: index + 1 }) }))
        );

        it('cuts the requested page out of the result', () => {
            expect(pageRows(rows, 2, 10).length).toBe(2);
        });

        it('yields nothing for a page beyond the result', () => {
            expect(pageRows(rows, 5, 10)).toEqual([]);
        });

        it('falls back to the last page that still exists', () => {
            expect(clampPage(5, 12, 10)).toBe(2);
            expect(clampPage(2, 0, 10)).toBe(1);
            expect(clampPage(1, 12, 10)).toBe(1);
        });
    });
});
