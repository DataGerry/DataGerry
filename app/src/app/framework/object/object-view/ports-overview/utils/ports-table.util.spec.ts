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
import { FieldOption } from 'src/app/framework/models/cmdb-section-template';
import { Sort, SortDirection } from 'src/app/layout/table/table.types';
import {
    CableSource,
    CmdbPortConnection,
    ConnectionType,
    PortConnectionState,
    ResolvedCable
} from '../models/port-connection.types';
import { CmdbPort, PortSide } from '../models/ports-overview.types';
import { indexConnectionsByPort } from './port-connection.util';
import {
    clampPage,
    hasConnectionState,
    hasPanelSides,
    pagePortRows,
    sortPortRows,
    toOptionLabels,
    toPortRows
} from './ports-table.util';
/* ------------------------------------------------------------------------------------------------------------------ */

function port(overrides: Partial<CmdbPort> = {}): CmdbPort {
    return {
        public_id: 1,
        object_id: 8802,
        side: PortSide.SINGLE,
        name: 'Gi1/0/1',
        port_number: 1,
        status: null,
        port_type: null,
        speed: null,
        description: null,
        author_id: 1,
        creation_time: null,
        last_edit_time: null,
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

function connection(overrides: Partial<CmdbPortConnection> = {}): CmdbPortConnection {
    return {
        public_id: 1,
        endpoints: [1, 2],
        connection_type: ConnectionType.CABLE,
        cable: cable(),
        author_id: 1,
        creation_time: null,
        last_edit_time: null,
        ...overrides
    };
}

const BY_NAME: Sort = { name: 'name', order: SortDirection.ASCENDING };


describe('ports-table.util', () => {

    describe('toOptionLabels', () => {
        it('flattens every option type into one public_id lookup', () => {
            const options = new Map<string, FieldOption[]>([
                ['PORT_STATUS', [{ name: '7', label: 'Up' }]],
                ['PORT_SPEED', [{ name: '25', label: '1G' }]]
            ]);

            expect(toOptionLabels(options).get('7')).toBe('Up');
            expect(toOptionLabels(options).get('25')).toBe('1G');
        });
    });


    describe('toPortRows', () => {
        it('resolves the option ids into their labels', () => {
            const labels = new Map([['7', 'Up'], ['10', 'RJ45'], ['25', '1G']]);

            const [row] = toPortRows([port({ status: 7, port_type: 10, speed: 25 })], labels);

            expect(row.status).toBe('Up');
            expect(row.portType).toBe('RJ45');
            expect(row.speed).toBe('1G');
        });

        it('keeps no label for an id whose option is gone, rather than showing the raw id', () => {
            const [row] = toPortRows([port({ status: 999 })], new Map());

            expect(row.status).toBeNull();
        });

        it('reads an unknown side as an ordinary device port', () => {
            const [row] = toPortRows([port({ side: 'somewhere' as PortSide })], new Map());

            expect(row.side).toBe(PortSide.SINGLE);
            expect(row.sideLabel).toBe('');
        });

        it('treats a missing connection state as not connected', () => {
            const [row] = toPortRows([port()], new Map());

            expect(row.connected).toBeFalse();
        });
    });


    describe('the connection cell', () => {
        const panel = [
            port({ public_id: 1, name: 'PP-01/F01', side: PortSide.FRONT }),
            port({ public_id: 2, name: 'PP-01/R01', side: PortSide.REAR })
        ];

        it('reads as free while nothing is connected', () => {
            const [row] = toPortRows(panel, new Map());

            expect(row.connectionState).toBe(PortConnectionState.FREE);
            expect(row.connectionLabel).toBe('Free');
            expect(row.cableConnectionId).toBeNull();
        });

        it('names the counterpart of an internal pairing, which belongs to the same object', () => {
            const connections = indexConnectionsByPort([
                connection({ endpoints: [1, 2], connection_type: ConnectionType.INTERNAL, cable: null })
            ]);

            const [front] = toPortRows(panel, new Map(), connections);

            expect(front.connectionState).toBe(PortConnectionState.PAIRED);
            expect(front.connectionLabel).toBe('Paired with PP-01/R01');
            expect(front.pairedPortName).toBe('PP-01/R01');
        });

        it('reads as its cable once one is attached, and offers that cable to edit', () => {
            const connections = indexConnectionsByPort([
                connection({
                    public_id: 7,
                    endpoints: [1, 99],
                    cable: cable({ name: 'Patch A-12', length: '3 m' })
                })
            ]);

            const [front] = toPortRows(panel, new Map(), connections);

            expect(front.connectionState).toBe(PortConnectionState.CABLED);
            expect(front.connectionLabel).toBe('Patch A-12 · 3 m');
            expect(front.cableConnectionId).toBe(7);
        });

        it('keeps the pairing of a panel port that also carries a cable', () => {
            const connections = indexConnectionsByPort([
                connection({ public_id: 7, endpoints: [1, 99] }),
                connection({
                    public_id: 8,
                    endpoints: [1, 2],
                    connection_type: ConnectionType.INTERNAL,
                    cable: null
                })
            ]);

            const [front] = toPortRows(panel, new Map(), connections);

            expect(front.connectionState).toBe(PortConnectionState.CABLED);
            expect(front.pairedPortName).toBe('PP-01/R01');
        });
    });


    describe('optional columns', () => {
        it('reports panel sides only when a port sits on a face', () => {
            const single = toPortRows([port()], new Map());
            const panel = toPortRows([port({ side: PortSide.REAR })], new Map());

            expect(hasPanelSides(single)).toBeFalse();
            expect(hasPanelSides(panel)).toBeTrue();
        });

        it('reports a connection state only when the backend sends the key', () => {
            expect(hasConnectionState([port()])).toBeFalse();
            expect(hasConnectionState([port({ connected: false })])).toBeTrue();
        });
    });


    describe('sortPortRows', () => {
        const rows = toPortRows([
            port({ public_id: 1, name: 'Gi1/0/2', port_number: 2, description: 'Uplink' }),
            port({ public_id: 2, name: 'Gi1/0/10', port_number: 10 }),
            port({ public_id: 3, name: 'Gi1/0/1', port_number: 1 })
        ], new Map());

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
            const mixed = toPortRows([
                port({ public_id: 1, description: null }),
                port({ public_id: 2, description: 'Patch panel' })
            ], new Map());

            const sorted = sortPortRows(mixed, { name: 'description', order: SortDirection.ASCENDING });

            expect(sorted.map(row => row.description)).toEqual(['Patch panel', null]);
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
        const rows = toPortRows(
            Array.from({ length: 12 }, (_, index) => port({ public_id: index + 1, port_number: index + 1 })),
            new Map()
        );

        it('cuts the requested page out of the result', () => {
            expect(pagePortRows(rows, 2, 10).length).toBe(2);
        });

        it('yields nothing for a page beyond the result', () => {
            expect(pagePortRows(rows, 5, 10)).toEqual([]);
        });

        it('falls back to the last page that still exists', () => {
            expect(clampPage(5, 12, 10)).toBe(2);
            expect(clampPage(2, 0, 10)).toBe(1);
            expect(clampPage(1, 12, 10)).toBe(1);
        });
    });
});
