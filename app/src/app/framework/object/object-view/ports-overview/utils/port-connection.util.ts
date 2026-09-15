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
    CmdbPortConnection,
    ConnectionEndpoint,
    ConnectionType,
    PortConnectionInfo,
    PortConnectionState
} from '../models/port-connection.types';
/* ------------------------------------------------------------------------------------------------------------------ */

const EMPTY_INFO: PortConnectionInfo = { state: PortConnectionState.FREE, cable: null, internal: null };


/**
 * Groups the connections of an object by the port each end belongs to.
 *
 * A panel port legitimately holds two: its cable and its internal pairing, which live under separate
 * cardinality guarantees. Both ends of every connection are indexed, because the stored pair is
 * sorted and neither position carries meaning.
 */
export function indexConnectionsByPort(connections: readonly CmdbPortConnection[]): Map<number, PortConnectionInfo> {
    const byPort = new Map<number, PortConnectionInfo>();

    for (const connection of connections) {
        for (const portId of connection.endpoints ?? []) {
            const info = byPort.get(portId) ?? { ...EMPTY_INFO };

            if (connection.connection_type === ConnectionType.INTERNAL) {
                info.internal = connection;
            } else {
                info.cable = connection;
            }

            info.state = info.cable ? PortConnectionState.CABLED
                : info.internal ? PortConnectionState.PAIRED
                : PortConnectionState.FREE;

            byPort.set(portId, info);
        }
    }

    return byPort;
}


/** The other end of a connection, seen from one of its ports. */
export function peerPortIdOf(connection: CmdbPortConnection | null, portId: number): number | null {
    const endpoints = connection?.endpoints ?? [];

    if (!endpoints.includes(portId)) {
        return null;
    }

    return endpoints.find((endpoint) => endpoint !== portId) ?? null;
}


/**
 * How a cable reads in one line: its name, its type and its length, whichever of them are filled in.
 *
 * Nothing has to be resolved here: the read routes answer with the same keys whether the values came
 * from the connection or from a linked CI, and `type` already arrives as a label.
 */
export function cableSummary(connection: CmdbPortConnection | null): string {
    const cable = connection?.cable;

    if (!cable) {
        return '';
    }

    const parts = [cable.name, cable.type, cable.length]
        .map((part) => part?.trim())
        .filter((part): part is string => !!part);

    return parts.join(' · ') || 'Cable';
}


/** One end of a connection in one line: the port, its side where the type has one, and its object. */
export function describeEndpoint(endpoint: ConnectionEndpoint | null): string | null {
    if (!endpoint) {
        return null;
    }

    const port = endpoint.sideLabel ? `${ endpoint.portName } (${ endpoint.sideLabel })` : endpoint.portName;

    return endpoint.objectLabel ? `${ port } - ${ endpoint.objectLabel }` : port;
}
