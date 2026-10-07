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
import { PortSide } from '../../ports-overview/models/ports-overview.types';
import { CablingSelection, CablingTrace } from '../models/cabling-spotlight.types';
import { CablingGraph } from '../models/cabling.types';
import {
    CABLE_FRONT,
    CABLE_NAS,
    CABLE_REAR,
    FRONT_12,
    NAS_01,
    NAS_E0A,
    PP_01,
    REAR_12,
    SW_01,
    SW_GI12,
    SW_GI24,
    SW_GI48,
    WEB_01,
    WEB_ETH0,
    WEB_ETH1,
    cablingEdge,
    cablingEnd,
    mockupRing,
    nasExpansion,
    switchNode
} from '../testing/cabling-fixtures';
import { graphFromRing, graphWithExpansion } from './cabling-graph.util';
import { spotlightTrace } from './cabling-spotlight.util';

describe('cabling-spotlight.util', () => {
    const CABLE_SIDE = 8904;

    /** PP-01's ring with SW-01's Gi1/0/24 followed to NAS-01. */
    const withNas = (): CablingGraph => graphWithExpansion(graphFromRing(mockupRing()), nasExpansion(), SW_GI24);

    /** PP-01's ring with WEB-01's eth1 followed to SW-01's Gi1/0/48: both ends one cable from PP-01. */
    const withSideCable = (): CablingGraph => graphWithExpansion(graphFromRing(mockupRing()), {
        focal_object_id: WEB_01,
        nodes: [switchNode()],
        edges: [cablingEdge(
            CABLE_SIDE,
            cablingEnd(WEB_01, WEB_ETH1, 'eth1', PortSide.SINGLE),
            cablingEnd(SW_01, SW_GI48, 'Gi1/0/48', PortSide.SINGLE)
        )]
    }, WEB_ETH1);

    const pick = (connectionId: number, objectId: number | null, portId: number | null): CablingSelection =>
        ({ connectionId, objectId, portId });

    const expectTrace = (trace: CablingTrace, connectionIds: number[], portIds: number[]) => {
        expect([...trace.connectionIds]).toEqual(jasmine.arrayWithExactContents(connectionIds));
        expect([...trace.portIds]).toEqual(jasmine.arrayWithExactContents(portIds));
    };

    it('lights the picked cable, its far end, and the cables back to the focal object', () => {
        expectTrace(
            spotlightTrace(withNas(), pick(CABLE_NAS, NAS_01, NAS_E0A)),
            [CABLE_NAS, CABLE_REAR],
            [NAS_E0A, SW_GI24, SW_GI12, REAR_12]
        );
    });

    it('lights the same trace from the end nearer the focal object', () => {
        expectTrace(
            spotlightTrace(withNas(), pick(CABLE_NAS, SW_01, SW_GI24)),
            [CABLE_NAS, CABLE_REAR],
            [NAS_E0A, SW_GI24, SW_GI12, REAR_12]
        );
    });

    it('stops at the focal object, so its other cables stay dark', () => {
        expectTrace(spotlightTrace(withNas(), pick(CABLE_REAR, SW_01, SW_GI12)), [CABLE_REAR], [SW_GI12, REAR_12]);
        expectTrace(spotlightTrace(withNas(), pick(CABLE_REAR, PP_01, REAR_12)), [CABLE_REAR], [SW_GI12, REAR_12]);
    });

    it('walks back from the picked card when both ends are as far from the focal object', () => {
        expectTrace(
            spotlightTrace(withSideCable(), pick(CABLE_SIDE, WEB_01, WEB_ETH1)),
            [CABLE_SIDE, CABLE_FRONT],
            [WEB_ETH1, SW_GI48, WEB_ETH0, FRONT_12]
        );
        expectTrace(
            spotlightTrace(withSideCable(), pick(CABLE_SIDE, SW_01, SW_GI48)),
            [CABLE_SIDE, CABLE_REAR],
            [WEB_ETH1, SW_GI48, SW_GI12, REAR_12]
        );
    });

    it('marks only the picked port while its cable is not drawn', () => {
        expectTrace(spotlightTrace(graphFromRing(mockupRing()), pick(CABLE_NAS, SW_01, SW_GI24)), [CABLE_NAS], [SW_GI24]);
    });

    it('lights only the cable when its line is picked rather than a port', () => {
        expectTrace(spotlightTrace(withNas(), pick(CABLE_NAS, null, null)), [CABLE_NAS], []);
    });
});
