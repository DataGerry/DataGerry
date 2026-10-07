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
import { PortDeviceKind } from '../../ports-overview/models/port-bulk.types';
import { CableSource, ResolvedCable } from '../../ports-overview/models/port-connection.types';
import { OverviewPort, PortSide } from '../../ports-overview/models/ports-overview.types';
import {
    CablingEdge,
    CablingEnd,
    CablingResponse,
    ReadableCablingNode,
    RestrictedCablingNode
} from '../models/cabling.types';
/* ------------------------------------------------------------------------------------------------------------------ */

/** Object ids : PP-01 in the middle, WEB-01 on its front, SW-01 on its rear, NAS-01 and BACKUP-01 beyond. */
export const PP_01 = 8701;
export const SW_01 = 8702;
export const WEB_01 = 8703;
export const NAS_01 = 8704;
export const BACKUP_01 = 8706;

export const FRONT_12 = 8804;
export const REAR_12 = 8803;
export const WEB_ETH0 = 8807;
export const WEB_ETH1 = 8808;
export const SW_GI12 = 8806;
export const SW_GI24 = 8809;
export const SW_GI48 = 8811;
export const NAS_E0A = 8812;
export const NAS_E0B = 8813;
export const BACKUP_ETH0 = 8814;

export const CABLE_FRONT = 8901;
export const CABLE_REAR = 8902;
export const CABLE_NAS = 8903;
export const CABLE_BACKUP = 8907;


export function resolvedCable(overrides: Partial<ResolvedCable> = {}): ResolvedCable {
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


export function overviewPort(portId: number, name: string, overrides: Partial<OverviewPort> = {}): OverviewPort {
    return {
        port_id: portId,
        side: PortSide.SINGLE,
        port_number: null,
        name,
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


/** A port whose cable reaches `farPortId` on `farObjectId`. */
export function cabledPort(
    portId: number,
    name: string,
    far: { objectId: number; label: string; portId: number; portName: string; side?: PortSide },
    connectionId: number,
    cable: ResolvedCable = resolvedCable({ name: `CABLE-${ connectionId }` }),
    overrides: Partial<OverviewPort> = {}
): OverviewPort {
    return overviewPort(portId, name, {
        connected: true,
        cable,
        cable_connection_id: connectionId,
        connected_port: { port_id: far.portId, name: far.portName, side: far.side ?? PortSide.SINGLE },
        connected_object: { object_id: far.objectId, label: far.label, restricted: false },
        ...overrides
    });
}


export function standardNode(objectId: number, title: string, ports: OverviewPort[]): ReadableCablingNode {
    return {
        object_id: objectId,
        restricted: false,
        title,
        type_info: { type_id: 8610, type_color: '#1f77b4', label: 'Device', icon: 'fas fa-server' },
        device_kind: ports.length ? PortDeviceKind.STANDARD : null,
        port_count: ports.length,
        rows: ports.map((port) => ({ port }))
    };
}


export function panelNode(
    objectId: number,
    title: string,
    pairs: Array<{ front: OverviewPort | null; rear: OverviewPort | null; paired: boolean }>
): ReadableCablingNode {
    return {
        object_id: objectId,
        restricted: false,
        title,
        type_info: { type_id: 8611, type_color: '#ff7f0e', label: 'Patchpanel', icon: 'fa-grip' },
        device_kind: PortDeviceKind.PATCH_PANEL,
        port_count: pairs.reduce((count, pair) => count + Number(!!pair.front) + Number(!!pair.rear), 0),
        rows: pairs
    };
}


export function restrictedNode(objectId: number): RestrictedCablingNode {
    return { object_id: objectId, restricted: true };
}


export function cablingEnd(objectId: number, portId: number, portName: string | null, side: PortSide | null): CablingEnd {
    return { object_id: objectId, port_id: portId, port_name: portName, side };
}


export function cablingEdge(
    connectionId: number,
    from: CablingEnd,
    to: CablingEnd,
    cable: ResolvedCable = resolvedCable({ name: `CABLE-${ connectionId }` })
): CablingEdge {
    return { connection_id: connectionId, from, to, cable };
}

/* ------------------------------------------------------------------------------------------------------------------ */

const cat6Front = resolvedCable({ name: 'CAT6-001', length: '2 m', color: 'blue' });
const cat6Rear = resolvedCable({ name: 'CAT6-003', length: '15 m', color: 'blue' });
const om4 = resolvedCable({ name: 'OM4-001', length: '35 m', color: 'purple', type: 'OM4' });

export const ppNode = (): ReadableCablingNode => panelNode(PP_01, 'PP-01', [{
    front: cabledPort(FRONT_12, 'Front 12', {
        objectId: WEB_01, label: 'Device #8703 - WEB-01', portId: WEB_ETH0, portName: 'eth0'
    }, CABLE_FRONT, cat6Front, { side: PortSide.FRONT, port_number: 12 }),
    rear: cabledPort(REAR_12, 'Rear 12', {
        objectId: SW_01, label: 'Device #8702 - SW-01', portId: SW_GI12, portName: 'Gi1/0/12'
    }, CABLE_REAR, cat6Rear, { side: PortSide.REAR, port_number: 12 }),
    paired: true
}]);

export const webNode = (): ReadableCablingNode => standardNode(WEB_01, 'WEB-01', [
    cabledPort(WEB_ETH0, 'eth0', {
        objectId: PP_01, label: 'Patchpanel #8701 - PP-01', portId: FRONT_12, portName: 'Front 12', side: PortSide.FRONT
    }, CABLE_FRONT, cat6Front),
    overviewPort(WEB_ETH1, 'eth1')
]);

export const switchNode = (): ReadableCablingNode => standardNode(SW_01, 'SW-01', [
    cabledPort(SW_GI12, 'Gi1/0/12', {
        objectId: PP_01, label: 'Patchpanel #8701 - PP-01', portId: REAR_12, portName: 'Rear 12', side: PortSide.REAR
    }, CABLE_REAR, cat6Rear),
    cabledPort(SW_GI24, 'Gi1/0/24', {
        objectId: NAS_01, label: 'Device #8704 - NAS-01', portId: NAS_E0A, portName: 'e0a'
    }, CABLE_NAS, om4),
    overviewPort(SW_GI48, 'Gi1/0/48')
]);

export const nasNode = (): ReadableCablingNode => standardNode(NAS_01, 'NAS-01', [
    cabledPort(NAS_E0A, 'e0a', {
        objectId: SW_01, label: 'Device #8702 - SW-01', portId: SW_GI24, portName: 'Gi1/0/24'
    }, CABLE_NAS, om4),
    overviewPort(NAS_E0B, 'e0b')
]);

export const frontEdge = (): CablingEdge => cablingEdge(
    CABLE_FRONT,
    cablingEnd(PP_01, FRONT_12, 'Front 12', PortSide.FRONT),
    cablingEnd(WEB_01, WEB_ETH0, 'eth0', PortSide.SINGLE),
    cat6Front
);

export const rearEdge = (): CablingEdge => cablingEdge(
    CABLE_REAR,
    cablingEnd(PP_01, REAR_12, 'Rear 12', PortSide.REAR),
    cablingEnd(SW_01, SW_GI12, 'Gi1/0/12', PortSide.SINGLE),
    cat6Rear
);

export const nasEdge = (): CablingEdge => cablingEdge(
    CABLE_NAS,
    cablingEnd(SW_01, SW_GI24, 'Gi1/0/24', PortSide.SINGLE),
    cablingEnd(NAS_01, NAS_E0A, 'e0a', PortSide.SINGLE),
    om4
);

/** `GET /ports/object/8701/cabling`, as the route documentation shows it. */
export const mockupRing = (): CablingResponse => ({
    focal_object_id: PP_01,
    nodes: [ppNode(), webNode(), switchNode()],
    edges: [frontEdge(), rearEdge()]
});

/** `GET /ports/8809/cabling`: following SW-01's Gi1/0/24 reveals NAS-01. */
export const nasExpansion = (): CablingResponse => ({
    focal_object_id: SW_01,
    nodes: [nasNode()],
    edges: [nasEdge()]
});


/** `GET /ports/8813/cabling`: following NAS-01's e0b reveals BACKUP-01. */
export const backupExpansion = (): CablingResponse => ({
    focal_object_id: NAS_01,
    nodes: [standardNode(BACKUP_01, 'BACKUP-01', [
        cabledPort(BACKUP_ETH0, 'eth0', { objectId: NAS_01, label: 'Device #8704 - NAS-01', portId: NAS_E0B, portName: 'e0b' }, CABLE_BACKUP)
    ])],
    edges: [cablingEdge(
        CABLE_BACKUP,
        cablingEnd(NAS_01, NAS_E0B, 'e0b', PortSide.SINGLE),
        cablingEnd(BACKUP_01, BACKUP_ETH0, 'eth0', PortSide.SINGLE)
    )]
});
