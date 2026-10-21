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
import { PortSide } from '../../../ports-overview/models/ports-overview.types';
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
    SW_GI24,
    WEB_01,
    WEB_ETH0,
    frontEdge,
    mockupRing,
    nasExpansion,
    ppNode,
    rearEdge,
    restrictedNode,
    switchNode,
    webNode
} from '../testing/cabling-fixtures';
import { graphFromRing, graphWithExpansion, nodePorts, revealColumn, revealedObjectIds } from './cabling-graph.util';

describe('cabling-graph.util', () => {

    describe('revealColumn', () => {
        it('puts what a panel front reaches on its left and what its rear reaches on its right', () => {
            expect(revealColumn(0, PortSide.FRONT, PortSide.SINGLE, 0, 0)).toBe(-1);
            expect(revealColumn(0, PortSide.REAR, PortSide.SINGLE, 0, 0)).toBe(1);
        });

        it('faces a revealed panel towards the node it was reached from', () => {
            expect(revealColumn(0, PortSide.SINGLE, PortSide.FRONT, 0, 0)).toBe(1);
            expect(revealColumn(0, PortSide.SINGLE, PortSide.REAR, 0, 0)).toBe(-1);
        });

        it('lets the parent face decide when both ends sit on a panel', () => {
            expect(revealColumn(2, PortSide.REAR, PortSide.REAR, 0, 0)).toBe(3);
        });

        it('keeps walking away from the focal object between two plain ports', () => {
            expect(revealColumn(1, PortSide.SINGLE, PortSide.SINGLE, 0, 0)).toBe(2);
            expect(revealColumn(-2, null, null, 0, 0)).toBe(-3);
        });

        it('fills the emptier side beside the focal object, right first', () => {
            expect(revealColumn(0, PortSide.SINGLE, PortSide.SINGLE, 0, 0)).toBe(1);
            expect(revealColumn(0, PortSide.SINGLE, PortSide.SINGLE, 0, 1)).toBe(-1);
            expect(revealColumn(0, PortSide.SINGLE, PortSide.SINGLE, 2, 1)).toBe(1);
        });
    });

    describe('graphFromRing', () => {
        it('centres the focal object and places each neighbour by the panel face its cable lands on', () => {
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

        it('puts the focal object first even when the response lists it later', () => {
            const ring = mockupRing();
            const graph = graphFromRing({ ...ring, nodes: [...ring.nodes].reverse() });

            expect([...graph.nodes.keys()][0]).toBe(PP_01);
        });

        it('keeps one edge per cable', () => {
            expect([...graphFromRing(mockupRing()).edges.keys()]).toEqual([CABLE_FRONT, CABLE_REAR]);
        });

        it('recovers a cable between two drawn objects from their rows when the edge list misses it', () => {
            const graph = graphFromRing({ ...mockupRing(), edges: [] });

            expect(graph.edges.get(CABLE_REAR)?.from.port_id).toBe(REAR_12);
            expect(graph.reveals.get(SW_01)?.parentPortId).toBe(REAR_12);
        });

        it('draws no edge towards an object that is not on the canvas', () => {
            const graph = graphFromRing(mockupRing());

            expect(graph.edges.has(CABLE_NAS)).toBeFalse();
        });
    });

    describe('graphWithExpansion', () => {
        it('keeps the canvas to three columns: a card that would open a fourth joins its parent', () => {
            const graph = graphWithExpansion(graphFromRing(mockupRing()), nasExpansion(), SW_GI24);

            expect(graph.reveals.get(NAS_01)).toEqual(
                { parentId: SW_01, parentPortId: SW_GI24, ownPortId: NAS_E0A, column: 1, generation: 2 }
            );
            expect(graph.edges.has(CABLE_NAS)).toBeTrue();
        });

        it('opens a third column while the canvas has two, and no fourth', () => {
            const ring = graphFromRing({ focal_object_id: WEB_01, nodes: [webNode(), ppNode()], edges: [frontEdge()] });
            const graph = graphWithExpansion(
                ring, { focal_object_id: PP_01, nodes: [switchNode()], edges: [rearEdge()] }, REAR_12
            );
            const further = graphWithExpansion(graph, nasExpansion(), SW_GI24);

            expect(ring.reveals.get(PP_01)?.column).toBe(1);
            expect(graph.reveals.get(SW_01)?.column).toBe(2);
            expect(further.reveals.get(NAS_01)?.column).toBe(2);
        });

        it('keeps the place of a node already drawn and takes its fresher rows', () => {
            const ring = graphFromRing(mockupRing());
            const fresher = { ...webNode(), title: 'WEB-01 (renamed)' };
            const graph = graphWithExpansion(ring, { focal_object_id: PP_01, nodes: [fresher], edges: [] }, FRONT_12);

            expect(graph.reveals.get(WEB_01)).toBe(ring.reveals.get(WEB_01));
            expect(graph.nodes.get(WEB_01)).toBe(fresher);
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
