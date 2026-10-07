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
import { CablingEdge, CablingResponse, CablingReveal } from '../models/cabling.types';
import {
    BACKUP_01,
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
    backupExpansion,
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
        const focal: CablingReveal = { parentId: null, parentPortId: null, ownPortId: null, column: 0, generation: 0 };
        const at = (column: number): CablingReveal => ({ parentId: PP_01, parentPortId: null, ownPortId: null, column, generation: 1 });

        it('puts what a panel\'s front reaches on its left and what its rear reaches on its right', () => {
            expect(revealColumn(focal, PortSide.FRONT, false)).toBe(-1);
            expect(revealColumn(focal, PortSide.REAR, false)).toBe(1);
            expect(revealColumn(at(1), PortSide.REAR, true)).toBe(2);
            expect(revealColumn(at(-1), PortSide.FRONT, false)).toBe(-2);
        });

        it('stands a panel cabled to a plain focal object in the focal column', () => {
            expect(revealColumn(focal, null, true)).toBe(0);
        });

        it('steps a panel reached from a plain device one column back towards the focal object', () => {
            expect(revealColumn(at(1), null, true)).toBe(0);
            expect(revealColumn(at(2), null, true)).toBe(1);
            expect(revealColumn(at(-1), null, true)).toBe(0);
            expect(revealColumn(at(-2), null, true)).toBe(-1);
        });

        it('flows right from a plain focal object and on away from it', () => {
            expect(revealColumn(focal, null, false)).toBe(1);
            expect(revealColumn(at(1), null, false)).toBe(2);
            expect(revealColumn(at(-1), null, false)).toBe(-2);
        });

        it('keeps a card past the outer columns in its parent\'s', () => {
            expect(revealColumn(at(2), null, false)).toBe(2);
            expect(revealColumn(at(-2), null, false)).toBe(-2);
            expect(revealColumn(at(2), PortSide.REAR, false)).toBe(2);
            expect(revealColumn(at(-2), PortSide.FRONT, false)).toBe(-2);
        });
    });

    describe('graphFromRing', () => {
        it('starts at a focal panel and puts what its front reaches on its left, what its rear reaches on its right', () => {
            const graph = graphFromRing(mockupRing());

            expect(graph.focalId).toBe(PP_01);
            expect(graph.reveals.get(PP_01)).toEqual(
                { parentId: null, parentPortId: null, ownPortId: null, column: 0, generation: 0 }
            );
            expect(graph.reveals.get(WEB_01)).toEqual(
                { parentId: PP_01, parentPortId: FRONT_12, ownPortId: WEB_ETH0, column: -1, generation: 1 }
            );
            expect(graph.reveals.get(SW_01)?.column).toBe(1);
        });

        it('stands a patch panel neighbour in the focal column', () => {
            const graph = graphFromRing({ focal_object_id: WEB_01, nodes: [webNode(), ppNode()], edges: [frontEdge()] });

            expect(graph.reveals.get(PP_01)?.column).toBe(0);
        });

        it('treats a restricted neighbour as a plain device', () => {
            const graph = graphFromRing({ focal_object_id: WEB_01, nodes: [webNode(), restrictedNode(PP_01)], edges: [frontEdge()] });

            expect(graph.reveals.get(PP_01)?.column).toBe(1);
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

        it('follows a panel standing above the focal object out of its front to the left and its rear to the right', () => {
            const fromWeb = graphFromRing({ focal_object_id: WEB_01, nodes: [webNode(), ppNode()], edges: [frontEdge()] });
            const fromSwitch = graphFromRing({ focal_object_id: SW_01, nodes: [switchNode(), ppNode()], edges: [rearEdge()] });
            const rearFollowed = graphWithExpansion(fromWeb, { focal_object_id: PP_01, nodes: [switchNode()], edges: [rearEdge()] }, REAR_12);
            const frontFollowed = graphWithExpansion(fromSwitch, { focal_object_id: PP_01, nodes: [webNode()], edges: [frontEdge()] }, FRONT_12);

            expect(rearFollowed.reveals.get(SW_01)?.column).toBe(1);
            expect(frontFollowed.reveals.get(WEB_01)?.column).toBe(-1);
        });

        it('flows on away from the focal object, no further than the outer column', () => {
            const nas = graphWithExpansion(graphFromRing(mockupRing()), nasExpansion(), SW_GI24);
            const backup = graphWithExpansion(nas, backupExpansion(), NAS_E0B);

            expect(backup.reveals.get(BACKUP_01)?.column).toBe(2);
            expect(backup.reveals.get(BACKUP_01)?.parentId).toBe(NAS_01);
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
