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
import {
    CableSource,
    CmdbPortConnection,
    ConnectionType,
    PortConnectionState,
    ResolvedCable
} from '../models/port-connection.types';
import { cableSummary, indexConnectionsByPort, peerPortIdOf } from './port-connection.util';
/* ------------------------------------------------------------------------------------------------------------------ */

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
        endpoints: [9940, 9942],
        connection_type: ConnectionType.CABLE,
        cable: cable(),
        author_id: 1,
        creation_time: null,
        last_edit_time: null,
        ...overrides
    };
}


describe('port-connection.util', () => {

    describe('indexConnectionsByPort', () => {
        it('indexes both ends, because neither position of the sorted pair means anything', () => {
            const byPort = indexConnectionsByPort([connection()]);

            expect(byPort.get(9940).state).toBe(PortConnectionState.CABLED);
            expect(byPort.get(9942).state).toBe(PortConnectionState.CABLED);
        });

        it('keeps a panel port\'s cable and its internal pairing apart', () => {
            const byPort = indexConnectionsByPort([
                connection({ public_id: 1, endpoints: [9940, 9942] }),
                connection({ public_id: 2, endpoints: [9940, 9941], connection_type: ConnectionType.INTERNAL })
            ]);

            const port = byPort.get(9940);

            expect(port.cable.public_id).toBe(1);
            expect(port.internal.public_id).toBe(2);
        });

        it('reports a port that is only paired as paired, never as cabled', () => {
            const byPort = indexConnectionsByPort([
                connection({ endpoints: [9940, 9941], connection_type: ConnectionType.INTERNAL })
            ]);

            expect(byPort.get(9941).state).toBe(PortConnectionState.PAIRED);
        });

        it('has no entry for a port nothing is connected to', () => {
            expect(indexConnectionsByPort([]).get(9940)).toBeUndefined();
        });
    });


    describe('peerPortIdOf', () => {
        it('answers the other end, from either side', () => {
            expect(peerPortIdOf(connection(), 9940)).toBe(9942);
            expect(peerPortIdOf(connection(), 9942)).toBe(9940);
        });

        it('answers nothing for a port that is not an endpoint', () => {
            expect(peerPortIdOf(connection(), 1)).toBeNull();
            expect(peerPortIdOf(null, 9940)).toBeNull();
        });
    });


    describe('cableSummary', () => {
        it('reads as name, type and length, separated', () => {
            const summary = cableSummary(connection({
                cable: cable({ name: 'Patch A-12', type: 'CAT6A', type_id: 9932, length: '3 m' })
            }));

            expect(summary).toBe('Patch A-12 · CAT6A · 3 m');
        });

        it('leaves out what is not filled in', () => {
            expect(cableSummary(connection({ cable: cable({ length: '3 m' }) }))).toBe('3 m');
        });

        it('reads an inventoried cable exactly like an inline one - the route resolves both alike', () => {
            const summary = cableSummary(connection({
                cable: cable({
                    source: CableSource.CI,
                    cable_ci_id: 9950,
                    name: 'CAB-000471',
                    type: 'CAT6',
                    length: '3 m'
                })
            }));

            expect(summary).toBe('CAB-000471 · CAT6 · 3 m');
        });

        it('still names a cable that carries no information at all', () => {
            expect(cableSummary(connection())).toBe('Cable');
        });

        it('says nothing for a link that has no cable, such as a panel pairing', () => {
            expect(cableSummary(connection({ cable: null }))).toBe('');
        });
    });
});
