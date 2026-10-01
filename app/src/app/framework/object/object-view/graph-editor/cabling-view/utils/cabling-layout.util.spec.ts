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
import { CABLING_GEOMETRY, DEFAULT_DISPLAY_OPTIONS } from '../constants/cabling.constants';
import { CablingDisplayOptions, CablingGraph, CablingNodeLayout } from '../models/cabling.types';
import {
    CABLE_FRONT,
    CABLE_NAS,
    CABLE_REAR,
    NAS_01,
    PP_01,
    SW_01,
    SW_GI24,
    WEB_01,
    cabledPort,
    cablingEdge,
    cablingEnd,
    mockupRing,
    nasExpansion,
    overviewPort,
    restrictedNode,
    standardNode
} from '../testing/cabling-fixtures';
import { graphFromRing, graphWithExpansion } from './cabling-graph.util';
import {
    anchorOffset,
    cablingBounds,
    layoutCablingEdges,
    layoutCablingNodes,
    offsetCablingNodes
} from './cabling-layout.util';

describe('cabling-layout.util', () => {
    const options = (overrides: Partial<CablingDisplayOptions> = {}): CablingDisplayOptions =>
        ({ ...DEFAULT_DISPLAY_OPTIONS, ...overrides });

    const layout = (graph: CablingGraph, overrides: Partial<CablingDisplayOptions> = {}, expanded: number[] = []) =>
        layoutCablingNodes(graph, options(overrides), new Set(expanded));

    const overlaps = (first: CablingNodeLayout, second: CablingNodeLayout) =>
        first.x < second.x + second.width && second.x < first.x + first.width
        && first.y < second.y + second.height && second.y < first.y + first.height;

    /** A switch on the focal side with `count` ports, the first `cabled` of them to servers. */
    const busySwitch = (count: number, cabled: number) => standardNode(9000, 'SW-BIG', Array.from({ length: count }, (_, index) =>
        index < cabled
            ? cabledPort(9100 + index, `Gi${ index }`, { objectId: 9200 + index, label: `SRV-${ index }`, portId: 9300 + index, portName: 'eth0' }, 9400 + index)
            : overviewPort(9100 + index, `Gi${ index }`)));

    describe('layoutCablingNodes', () => {
        it('lays the mockup out left to right: WEB-01, PP-01, SW-01', () => {
            const nodes = layout(graphFromRing(mockupRing()));

            expect(nodes.get(WEB_01).x).toBeLessThan(nodes.get(PP_01).x);
            expect(nodes.get(PP_01).x).toBeLessThan(nodes.get(SW_01).x);
        });

        it('keeps a gap for the cable label between two columns', () => {
            const nodes = layout(graphFromRing(mockupRing()));

            expect(nodes.get(PP_01).x - (nodes.get(WEB_01).x + nodes.get(WEB_01).width))
                .toBeGreaterThanOrEqual(CABLING_GEOMETRY.columnGap - 1);
        });

        it('makes a patch panel wider than a plain device, and both wider in the detail density', () => {
            const compact = layout(graphFromRing(mockupRing()));
            const detail = layout(graphFromRing(mockupRing()), { detail: true });

            expect(compact.get(PP_01).width).toBeGreaterThan(compact.get(WEB_01).width);
            expect(detail.get(WEB_01).width).toBeGreaterThan(compact.get(WEB_01).width);
        });

        it('folds the rows past the compact limit under a count of the ports left', () => {
            const graph = graphFromRing({
                focal_object_id: 9000,
                nodes: [busySwitch(5, 0)],
                edges: []
            });
            const folded = layout(graph).get(9000);
            const unfolded = layout(graph, {}, [9000]).get(9000);

            expect(folded.rows.length).toBe(3);
            expect(folded.footer).toEqual(jasmine.objectContaining({ hiddenPorts: 2, expanded: false }));
            expect(unfolded.rows.length).toBe(5);
            expect(unfolded.footer?.expanded).toBeTrue();
            expect(unfolded.height).toBeGreaterThan(folded.height);
        });

        it('meets a folded port at the line that unfolds it', () => {
            const graph = graphFromRing({ focal_object_id: 9000, nodes: [busySwitch(5, 5)], edges: [] });
            const card = layout(graph).get(9000);

            expect(anchorOffset(card, 9104)).toBe(card.footer.top + CABLING_GEOMETRY.footerHeight / 2);
            expect(anchorOffset(card, 9100)).toBe(card.rows[0].top + card.rows[0].height / 2);
        });

        it('drops the free ports when only connected ports are shown', () => {
            const nodes = layout(graphFromRing(mockupRing()), { onlyConnected: true });

            expect(nodes.get(SW_01).rows.map((row) => row.port?.name)).toEqual(['Gi1/0/12', 'Gi1/0/24']);
        });

        it('says so when a filter leaves a card without rows', () => {
            const graph = graphFromRing({
                focal_object_id: 9000,
                nodes: [standardNode(9000, 'SPARE', [overviewPort(9100, 'Gi0')])],
                edges: []
            });

            expect(layout(graph, { onlyConnected: true }).get(9000).emptyMessage).toBe('No connected ports');
            expect(layout(graphFromRing({
                focal_object_id: 9000, nodes: [standardNode(9000, 'EMPTY', [])], edges: []
            })).get(9000).emptyMessage).toBe('No ports');
        });

        it('shrinks every card to its header when the ports are hidden', () => {
            const card = layout(graphFromRing(mockupRing()), { showPorts: false }).get(SW_01);

            expect(card.height).toBe(CABLING_GEOMETRY.headerHeight);
            expect(card.rows).toEqual([]);
            expect(anchorOffset(card, SW_GI24)).toBe(CABLING_GEOMETRY.headerHeight / 2);
        });

        it('describes a restricted object by that fact alone', () => {
            const graph = graphFromRing({
                focal_object_id: SW_01,
                nodes: [
                    standardNode(SW_01, 'SW-01', [cabledPort(8811, 'Gi1/0/48', { objectId: 8705, label: null, portId: 8810, portName: null }, 8905)]),
                    restrictedNode(8705)
                ],
                edges: [cablingEdge(8905, cablingEnd(SW_01, 8811, 'Gi1/0/48', null), cablingEnd(8705, 8810, null, null))]
            });
            const card = layout(graph).get(8705);

            expect(card.restricted).toBeTrue();
            expect(card.title).toBe('Restricted object');
            expect(card.title).not.toContain('8705');
            expect(card.rows).toEqual([]);
        });

        it('offers to follow a cable only while its far end is not drawn', () => {
            const ring = graphFromRing(mockupRing());
            const gi24 = (graph: CablingGraph) => layout(graph).get(SW_01).rows[1].port;

            expect(gi24(ring).expandable).toBeTrue();
            expect(gi24(graphWithExpansion(ring, nasExpansion(), SW_GI24)).expandable).toBeFalse();
        });

        it('stacks the neighbours sharing a column without letting them overlap', () => {
            const graph = graphFromRing({
                focal_object_id: 9000,
                nodes: [
                    busySwitch(6, 6),
                    ...Array.from({ length: 6 }, (_, index) => standardNode(9200 + index, `SRV-${ index }`, [
                        cabledPort(9300 + index, 'eth0', { objectId: 9000, label: 'SW-BIG', portId: 9100 + index, portName: `Gi${ index }` }, 9400 + index)
                    ]))
                ],
                edges: []
            });
            const cards = [...layout(graph).values()];

            cards.forEach((card, index) => cards.slice(index + 1).forEach((other) => {
                expect(overlaps(card, other)).withContext(`${ card.title } / ${ other.title }`).toBeFalse();
            }));
        });
    });

    describe('layoutCablingEdges', () => {
        const routed = (graph: CablingGraph) => {
            const nodes = layout(graph);

            return { nodes, edges: layoutCablingEdges(nodes, graph.edges.values()) };
        };

        it('runs a cable straight when both ends were placed level with each other', () => {
            const { edges } = routed(graphFromRing(mockupRing()));

            edges.forEach((edge) => expect(edge.from.y).withContext(edge.label).toBe(edge.to.y));
        });

        it('leaves a patch panel through its front on the left and its rear on the right', () => {
            const { nodes, edges } = routed(graphFromRing(mockupRing()));
            const panel = nodes.get(PP_01);

            expect(edges.find((edge) => edge.connectionId === CABLE_FRONT).from.x).toBe(panel.x);
            expect(edges.find((edge) => edge.connectionId === CABLE_REAR).from.x).toBe(panel.x + panel.width);
        });

        it('labels a cable by name and length and paints it in its own colour', () => {
            const { edges } = routed(graphFromRing(mockupRing()));
            const front = edges.find((edge) => edge.connectionId === CABLE_FRONT);

            expect(front.label).toBe('CAT6-001 · 2 m');
            expect(front.stroke).toBe('blue');
            expect(front.description).toBe('CAT6-001 · 2 m (blue): PP-01 Front 12 to WEB-01 eth0');
        });

        it('hangs a card held to its parent\'s column below the parent, its cable looping out on one side', () => {
            const graph = graphWithExpansion(graphFromRing(mockupRing()), nasExpansion(), SW_GI24);
            const { nodes, edges } = routed(graph);
            const sw = nodes.get(SW_01);
            const nas = nodes.get(NAS_01);
            const cable = edges.find((edge) => edge.connectionId === CABLE_NAS);

            expect(nas.x).toBe(sw.x);
            expect(nas.y).toBeGreaterThanOrEqual(sw.y + sw.height);
            expect(cable.from.x).toBe(sw.x + sw.width);
            expect(cable.to.x).toBe(nas.x + nas.width);
        });

        it('skips a cable whose far object is not on the canvas', () => {
            const graph = graphFromRing(mockupRing());
            const withoutSwitch = new Map(graph.nodes);
            withoutSwitch.delete(SW_01);

            expect(layoutCablingEdges(layout({ ...graph, nodes: withoutSwitch }), graph.edges.values()).length).toBe(1);
        });
    });

    describe('offsetCablingNodes', () => {
        it('moves the dragged card only', () => {
            const nodes = layout(graphFromRing(mockupRing()));
            const moved = offsetCablingNodes(nodes, new Map([[WEB_01, { x: 10, y: -20 }]]));

            expect(moved.get(WEB_01).x).toBe(nodes.get(WEB_01).x + 10);
            expect(moved.get(WEB_01).y).toBe(nodes.get(WEB_01).y - 20);
            expect(moved.get(PP_01)).toBe(nodes.get(PP_01));
        });
    });

    describe('cablingBounds', () => {
        it('spans every card', () => {
            const nodes = layout(graphFromRing(mockupRing()));
            const bounds = cablingBounds(nodes.values());

            expect(bounds.minX).toBe(nodes.get(WEB_01).x);
            expect(bounds.maxX).toBe(nodes.get(SW_01).x + nodes.get(SW_01).width);
        });

        it('has nothing to span on an empty canvas', () => {
            expect(cablingBounds([])).toBeNull();
        });
    });
});
