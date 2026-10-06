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
import { CablingEdge, CablingResponse } from '../models/cabling.types';
import {
    CABLE_FRONT,
    CABLE_NAS,
    CABLE_REAR,
    FRONT_12,
    NAS_01,
    NAS_E0A,
    NAS_E0B,
    PP_01,
    REAR_12,
    SW_01,
    SW_GI24,
    SW_GI48,
    WEB_01,
    WEB_ETH0,
    WEB_ETH1,
    cabledPort,
    cablingEdge,
    cablingEnd,
    frontEdge,
    mockupRing,
    nasExpansion,
    nasNode,
    ppNode,
    rearEdge,
    restrictedNode,
    switchNode,
    webNode
} from '../testing/cabling-fixtures';
import { graphFromRing, graphWithExpansion, nodePorts, revealColumn, revealedObjectIds } from './cabling-graph.util';

describe('cabling-graph.util', () => {
    const CABLE_SIDE = 8904;

    /** WEB-01's eth1 cabled straight to SW-01's Gi1/0/48, two neighbours of PP-01. */
    const sideEdge = (): CablingEdge => cablingEdge(
        CABLE_SIDE,
        cablingEnd(WEB_01, WEB_ETH1, 'eth1', PortSide.SINGLE),
        cablingEnd(SW_01, SW_GI48, 'Gi1/0/48', PortSide.SINGLE)
    );

    /** The mockup ring as the route answers it once WEB-01 and SW-01 are cabled to each other too. */
    const sideCabledRing = (): CablingResponse => {
        const web = webNode();
        web.rows[1] = {
            port: cabledPort(WEB_ETH1, 'eth1', { objectId: SW_01, label: 'SW-01', portId: SW_GI48, portName: 'Gi1/0/48' }, CABLE_SIDE)
        };

        return { focal_object_id: PP_01, nodes: [ppNode(), web, switchNode()], edges: [frontEdge(), rearEdge(), sideEdge()] };
    };

    describe('revealColumn', () => {
        it('puts every patch panel in the one column left of the focal object', () => {
            expect(revealColumn(0, true)).toBe(-1);
            expect(revealColumn(1, true)).toBe(-1);
            expect(revealColumn(-2, true)).toBe(-1);
        });

        it('flows right from the focal object and on from each neighbour', () => {
            expect(revealColumn(0, false)).toBe(1);
            expect(revealColumn(1, false)).toBe(2);
        });

        it('flows left from a panel', () => {
            expect(revealColumn(-1, false)).toBe(-2);
        });

        it('keeps a card past the outer columns in its parent\'s', () => {
            expect(revealColumn(2, false)).toBe(2);
            expect(revealColumn(-2, false)).toBe(-2);
        });
    });

    describe('graphFromRing', () => {
        it('starts at the focal object and puts every plain neighbour on its right, whichever face it is cabled to', () => {
            const graph = graphFromRing(mockupRing());

            expect(graph.focalId).toBe(PP_01);
            expect(graph.reveals.get(PP_01)).toEqual(
                { parentId: null, parentPortId: null, ownPortId: null, column: 0, generation: 0 }
            );
            expect(graph.reveals.get(WEB_01)).toEqual(
                { parentId: PP_01, parentPortId: FRONT_12, ownPortId: WEB_ETH0, column: 1, generation: 1 }
            );
            expect(graph.reveals.get(SW_01)?.column).toBe(1);
        });

        it('puts a patch panel neighbour on the left', () => {
            const graph = graphFromRing({ focal_object_id: WEB_01, nodes: [webNode(), ppNode()], edges: [frontEdge()] });

            expect(graph.reveals.get(PP_01)?.column).toBe(-1);
        });

        it('treats a restricted neighbour as a plain device', () => {
            const graph = graphFromRing({ focal_object_id: PP_01, nodes: [ppNode(), restrictedNode(SW_01)], edges: [rearEdge()] });

            expect(graph.reveals.get(SW_01)?.column).toBe(1);
        });

        it('puts the focal object first even when the response lists it later', () => {
            const ring = mockupRing();
            const graph = graphFromRing({ ...ring, nodes: [...ring.nodes].reverse() });

            expect([...graph.nodes.keys()][0]).toBe(PP_01);
        });

        it('keeps one edge per cable', () => {
            expect([...graphFromRing(mockupRing()).edges.keys()]).toEqual([CABLE_FRONT, CABLE_REAR]);
        });

        it('recovers a cable of the focal object from its rows when the edge list misses it', () => {
            const graph = graphFromRing({ ...mockupRing(), edges: [] });

            expect(graph.edges.get(CABLE_REAR)?.from.port_id).toBe(REAR_12);
            expect(graph.reveals.get(SW_01)?.parentPortId).toBe(REAR_12);
        });

        it('draws no edge towards an object that is not on the canvas', () => {
            const graph = graphFromRing(mockupRing());

            expect(graph.edges.has(CABLE_NAS)).toBeFalse();
        });

        it('leaves a cable between two neighbours undrawn, though the ring lists it', () => {
            expect([...graphFromRing(sideCabledRing()).edges.keys()]).toEqual([CABLE_FRONT, CABLE_REAR]);
        });
    });

    describe('graphWithExpansion', () => {
        it('follows a plain cable one column further right', () => {
            const graph = graphWithExpansion(graphFromRing(mockupRing()), nasExpansion(), SW_GI24);

            expect(graph.reveals.get(NAS_01)).toEqual(
                { parentId: SW_01, parentPortId: SW_GI24, ownPortId: NAS_E0A, column: 2, generation: 2 }
            );
            expect(graph.edges.has(CABLE_NAS)).toBeTrue();
        });

        it('flows left from a panel, and no further than one column beyond it', () => {
            const ring = graphFromRing({ focal_object_id: WEB_01, nodes: [webNode(), ppNode()], edges: [frontEdge()] });
            const graph = graphWithExpansion(
                ring, { focal_object_id: PP_01, nodes: [switchNode()], edges: [rearEdge()] }, REAR_12
            );
            const further = graphWithExpansion(graph, nasExpansion(), SW_GI24);

            expect(ring.reveals.get(PP_01)?.column).toBe(-1);
            expect(graph.reveals.get(SW_01)?.column).toBe(-2);
            expect(further.reveals.get(NAS_01)?.column).toBe(-2);
        });

        it('adds no second card for a node already drawn, keeps its place and takes its fresher rows', () => {
            const ring = graphFromRing(mockupRing());
            const fresher = { ...webNode(), title: 'WEB-01 (renamed)' };
            const graph = graphWithExpansion(ring, { focal_object_id: PP_01, nodes: [fresher], edges: [] }, FRONT_12);

            expect(graph.nodes.size).toBe(ring.nodes.size);
            expect(graph.reveals.get(WEB_01)).toBe(ring.reveals.get(WEB_01));
            expect(graph.nodes.get(WEB_01)).toBe(fresher);
        });

        it('draws a followed cable to an object already on the canvas without a second card', () => {
            const ring = graphFromRing(sideCabledRing());
            const graph = graphWithExpansion(ring, { focal_object_id: WEB_01, nodes: [switchNode()], edges: [sideEdge()] }, WEB_ETH1);

            expect(graph.edges.has(CABLE_SIDE)).toBeTrue();
            expect(graph.nodes.size).toBe(ring.nodes.size);
            expect(graph.reveals.get(SW_01)).toBe(ring.reveals.get(SW_01));
        });

        it('draws only the followed cable, none of the revealed object\'s other cables', () => {
            const nas = nasNode();
            nas.rows[1] = {
                port: cabledPort(NAS_E0B, 'e0b', { objectId: WEB_01, label: 'WEB-01', portId: WEB_ETH1, portName: 'eth1' }, CABLE_SIDE)
            };
            const graph = graphWithExpansion(graphFromRing(mockupRing()), { ...nasExpansion(), nodes: [nas] }, SW_GI24);

            expect([...graph.edges.keys()]).toEqual([CABLE_FRONT, CABLE_REAR, CABLE_NAS]);
        });

        it('leaves the graph it was given untouched', () => {
            const ring = graphFromRing(mockupRing());

            graphWithExpansion(ring, nasExpansion(), SW_GI24);

            expect(ring.nodes.has(NAS_01)).toBeFalse();
        });
    });

    describe('revealedObjectIds', () => {
        it('names only the objects not on the canvas yet', () => {
            const graph = graphFromRing(mockupRing());

            expect(revealedObjectIds(graph, nasExpansion())).toEqual([NAS_01]);
            expect(revealedObjectIds(graph, { focal_object_id: PP_01, nodes: [switchNode()], edges: [] })).toEqual([]);
        });
    });

    describe('nodePorts', () => {
        it('lists both faces of a panel row', () => {
            expect(nodePorts(ppNode()).map((port) => port.port_id)).toEqual([FRONT_12, REAR_12]);
        });

        it('has no ports to offer for a restricted object', () => {
            expect(nodePorts(restrictedNode(8705))).toEqual([]);
        });
    });
});
