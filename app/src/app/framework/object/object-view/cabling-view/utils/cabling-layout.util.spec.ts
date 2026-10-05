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
import { CABLING_GEOMETRY, DEFAULT_DISPLAY_OPTIONS } from '../constants/cabling.constants';
import {
    CablingDisplayOptions,
    CablingEdgeLayout,
    CablingGraph,
    CablingNodeLayout,
    CablingResponse
} from '../models/cabling.types';
import {
    CABLE_FRONT,
    CABLE_NAS,
    CABLE_REAR,
    FRONT_12,
    NAS_01,
    PP_01,
    REAR_12,
    SW_01,
    SW_GI12,
    SW_GI24,
    WEB_01,
    WEB_ETH0,
    WEB_ETH1,
    cabledPort,
    cablingEdge,
    cablingEnd,
    frontEdge,
    mockupRing,
    nasEdge,
    nasExpansion,
    nasNode,
    overviewPort,
    ppNode,
    rearEdge,
    restrictedNode,
    standardNode,
    switchNode,
    webNode
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
    const SW_GI1 = 8820;
    const CABLE_DIRECT = 8950;

    /** Free ports shown, so folding is tested on every row; the default hides them. */
    const options = (overrides: Partial<CablingDisplayOptions> = {}): CablingDisplayOptions =>
        ({ ...DEFAULT_DISPLAY_OPTIONS, onlyConnected: false, ...overrides });

    const layout = (graph: CablingGraph, overrides: Partial<CablingDisplayOptions> = {}, expanded: number[] = []) =>
        layoutCablingNodes(graph, options(overrides), new Set(expanded));

    const overlaps = (first: CablingNodeLayout, second: CablingNodeLayout) =>
        first.x < second.x + second.width && second.x < first.x + first.width
        && first.y < second.y + second.height && second.y < first.y + first.height;

    const within = (y: number, card: CablingNodeLayout) => y >= card.y && y <= card.y + card.height;

    /** A switch on the focal side with `count` ports, the first `cabled` of them to servers. */
    const busySwitch = (count: number, cabled: number) => standardNode(9000, 'SW-BIG', Array.from({ length: count }, (_, index) =>
        index < cabled
            ? cabledPort(9100 + index, `Gi${ index }`, { objectId: 9200 + index, label: `SRV-${ index }`, portId: 9300 + index, portName: 'eth0' }, 9400 + index)
            : overviewPort(9100 + index, `Gi${ index }`)));

    /** The servers at the far end of `busySwitch`, each cabled back to it. */
    const servers = (count: number) => Array.from({ length: count }, (_, index) => standardNode(9200 + index, `SRV-${ index }`, [
        cabledPort(9300 + index, 'eth0', { objectId: 9000, label: 'SW-BIG', portId: 9100 + index, portName: `Gi${ index }` }, 9400 + index)
    ]));

    const busyRing = (ports: number, cabled: number): CablingGraph => graphFromRing({
        focal_object_id: 9000,
        nodes: [busySwitch(ports, cabled), ...servers(cabled)],
        edges: []
    });

    /** SW-01 is cabled to PP-01's rear and straight to WEB-01, whose eth0 also reaches PP-01's front. */
    const crossRing = (): CablingResponse => ({
        focal_object_id: SW_01,
        nodes: [
            standardNode(SW_01, 'SW-01', [
                cabledPort(SW_GI12, 'Gi1/0/12', {
                    objectId: PP_01, label: 'PP-01', portId: REAR_12, portName: 'Rear 12', side: PortSide.REAR
                }, CABLE_REAR),
                cabledPort(SW_GI1, 'Gi1/0/1', { objectId: WEB_01, label: 'WEB-01', portId: WEB_ETH1, portName: 'eth1' }, CABLE_DIRECT)
            ]),
            ppNode(),
            standardNode(WEB_01, 'WEB-01', [
                cabledPort(WEB_ETH0, 'eth0', {
                    objectId: PP_01, label: 'PP-01', portId: FRONT_12, portName: 'Front 12', side: PortSide.FRONT
                }, CABLE_FRONT),
                cabledPort(WEB_ETH1, 'eth1', { objectId: SW_01, label: 'SW-01', portId: SW_GI1, portName: 'Gi1/0/1' }, CABLE_DIRECT)
            ])
        ],
        edges: [
            rearEdge(),
            cablingEdge(CABLE_DIRECT, cablingEnd(SW_01, SW_GI1, 'Gi1/0/1', PortSide.SINGLE), cablingEnd(WEB_01, WEB_ETH1, 'eth1', PortSide.SINGLE))
        ]
    });

    describe('layoutCablingNodes', () => {
        it('starts at the focal object and puts every plain neighbour in the column on its right', () => {
            const nodes = layout(graphFromRing(mockupRing()));

            expect(nodes.get(PP_01).x).toBeLessThan(nodes.get(WEB_01).x);
            expect(nodes.get(WEB_01).x).toBe(nodes.get(SW_01).x);
            expect(overlaps(nodes.get(WEB_01), nodes.get(SW_01))).toBeFalse();
        });

        it('puts a patch panel neighbour in the column left of the focal object', () => {
            const nodes = layout(graphFromRing({ focal_object_id: WEB_01, nodes: [webNode(), ppNode()], edges: [frontEdge()] }));

            expect(nodes.get(PP_01).x + nodes.get(PP_01).width).toBeLessThan(nodes.get(WEB_01).x);
        });

        it('keeps a gap for the cable label between two columns', () => {
            const nodes = layout(graphFromRing(mockupRing()));

            expect(nodes.get(WEB_01).x - (nodes.get(PP_01).x + nodes.get(PP_01).width))
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

        it('keeps three rows even when more are connected, folding the rest under a count', () => {
            const card = layout(busyRing(10, 5)).get(9000);

            expect(card.rows.map((row) => row.port?.name)).toEqual(['Gi0', 'Gi1', 'Gi2']);
            expect(card.footer?.hiddenPorts).toBe(7);
        });

        it('gives the rows whose cable is drawn the places first, in their own order', () => {
            const graph = graphFromRing({
                focal_object_id: 9000,
                nodes: [
                    standardNode(9000, 'SW-MIX', [
                        overviewPort(9100, 'Gi0'),
                        overviewPort(9101, 'Gi1'),
                        cabledPort(9102, 'Gi2', { objectId: 9202, label: 'SRV-2', portId: 9302, portName: 'eth0' }, 9402),
                        overviewPort(9103, 'Gi3'),
                        cabledPort(9104, 'Gi4', { objectId: 9204, label: 'SRV-4', portId: 9304, portName: 'eth0' }, 9404)
                    ]),
                    ...[2, 4].map((index) => standardNode(9200 + index, `SRV-${ index }`, [
                        cabledPort(9300 + index, 'eth0', { objectId: 9000, label: 'SW-MIX', portId: 9100 + index, portName: `Gi${ index }` }, 9400 + index)
                    ]))
                ],
                edges: []
            });
            const card = layout(graph).get(9000);

            expect(card.rows.map((row) => row.port?.name)).toEqual(['Gi0', 'Gi2', 'Gi4']);
            expect(card.footer?.hiddenPorts).toBe(2);
        });

        it('hides the free ports until they are asked for', () => {
            const graph = graphFromRing(mockupRing());
            const byDefault = layoutCablingNodes(graph, DEFAULT_DISPLAY_OPTIONS, new Set([SW_01])).get(SW_01);

            expect(byDefault.rows.map((row) => row.port?.name)).toEqual(['Gi1/0/12', 'Gi1/0/24']);
            expect(layout(graph, {}, [SW_01]).get(SW_01).rows.map((row) => row.port?.name))
                .toEqual(['Gi1/0/12', 'Gi1/0/24', 'Gi1/0/48']);
        });

        it('shows the free ports of a neighbour once free ports are shown', () => {
            expect(layout(graphFromRing(mockupRing())).get(SW_01).rows.map((row) => row.port?.name))
                .toEqual(['Gi1/0/12', 'Gi1/0/24', 'Gi1/0/48']);
        });

        it('drops the free ports when only connected ports are shown', () => {
            const nodes = layout(graphFromRing(mockupRing()), { onlyConnected: true }, [SW_01]);

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
            const gi24 = (graph: CablingGraph) => layout(graph, {}, [SW_01]).get(SW_01).rows[1].port;

            expect(gi24(ring).expandable).toBeTrue();
            expect(gi24(graphWithExpansion(ring, nasExpansion(), SW_GI24)).expandable).toBeFalse();
        });

        it('stacks the neighbours sharing a column without letting them overlap', () => {
            const cards = [...layout(busyRing(6, 6)).values()];

            expect(cards.some((card) => card.wrapped)).toBeFalse();
            cards.forEach((card, index) => cards.slice(index + 1).forEach((other) => {
                expect(overlaps(card, other)).withContext(`${ card.title } / ${ other.title }`).toBeFalse();
            }));
        });

        it('wraps a neighbours column past six cards into two sub-columns, alternating in port order', () => {
            const nodes = layout(busyRing(10, 10));
            const cards = [...nodes.values()];
            const wrapped = cards.filter((card) => card.wrapped);

            expect(wrapped.map((card) => card.title)).toEqual(['SRV-1', 'SRV-3', 'SRV-5', 'SRV-7', 'SRV-9']);
            expect(wrapped.every((card) => card.x > nodes.get(9200).x + nodes.get(9200).width)).toBeTrue();
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

        const cable = (edges: CablingEdgeLayout[], connectionId: number) => edges.find((edge) => edge.connectionId === connectionId);

        /** The two control points of a path's first curve. */
        const firstCurve = (path: string) => {
            const [fromX, fromY, toX, toY] = path.split('C')[1].split(/[ ,]+/).filter(Boolean).map(Number);

            return { from: { x: fromX, y: fromY }, to: { x: toX, y: toY } };
        };

        it('runs a cable straight when both ends were placed level with each other', () => {
            const { edges } = routed(graphFromRing({
                focal_object_id: SW_01, nodes: [switchNode(), ppNode(), nasNode()], edges: [rearEdge(), nasEdge()]
            }));

            expect(edges.length).toBe(2);
            edges.forEach((edge) => expect(edge.from.y).withContext(edge.label).toBe(edge.to.y));
        });

        it('leaves a patch panel through its front on the left and its rear on the right', () => {
            const { nodes, edges } = routed(graphFromRing(mockupRing()));
            const panel = nodes.get(PP_01);

            expect(cable(edges, CABLE_FRONT).from.x).toBe(panel.x);
            expect(cable(edges, CABLE_REAR).from.x).toBe(panel.x + panel.width);
        });

        it('turns a cable back around a panel whose front faces away from its peer', () => {
            const { nodes, edges } = routed(graphFromRing(mockupRing()));
            const panel = nodes.get(PP_01);
            const hook = firstCurve(cable(edges, CABLE_FRONT).path);

            expect(hook.from.x).toBeLessThan(panel.x);
            expect(within(hook.to.y, panel)).toBeFalse();
        });

        it('curves a cable between the two sides straight across, behind the focal object', () => {
            const { nodes, edges } = routed(graphFromRing(crossRing()));
            const front = cable(edges, CABLE_FRONT);

            expect(nodes.get(PP_01).x).toBeLessThan(nodes.get(SW_01).x);
            expect(nodes.get(WEB_01).x).toBeGreaterThan(nodes.get(SW_01).x);
            const focal = nodes.get(SW_01);

            expect(within(firstCurve(front.path).to.y, nodes.get(PP_01))).toBeFalse();
            expect(front.labelAt.x).toBeGreaterThan(focal.x);
            expect(front.labelAt.x).toBeLessThan(focal.x + focal.width);
            expect(within(front.labelAt.y, focal)).toBeTrue();
        });

        it('runs each cable to the second sub-column through a gap of the first', () => {
            const { nodes, edges } = routed(busyRing(10, 10));
            const inner = [...nodes.values()].filter((card) => !card.focal && !card.wrapped);
            const toWrapped = edges.filter((edge) => nodes.get(9200 + edge.connectionId - 9400).wrapped);

            expect(toWrapped.length).toBe(5);
            toWrapped.forEach((edge) => inner.forEach((card) => {
                expect(within(edge.to.y, card)).withContext(`${ edge.label } / ${ card.title }`).toBeFalse();
            }));
        });

        it('labels a cable by name and length and paints it in its own colour', () => {
            const { edges } = routed(graphFromRing(mockupRing()));
            const front = cable(edges, CABLE_FRONT);

            expect(front.label).toBe('CAT6-001 · 2 m');
            expect(front.stroke).toBe('blue');
            expect(front.description).toBe('CAT6-001 · 2 m (blue): PP-01 Front 12 to WEB-01 eth0');
        });

        it('hangs a card past the last column below its parent, its cable looping out on the outer side', () => {
            const ring = graphFromRing({ focal_object_id: WEB_01, nodes: [webNode(), ppNode()], edges: [frontEdge()] });
            const beyond = graphWithExpansion(ring, { focal_object_id: PP_01, nodes: [switchNode()], edges: [rearEdge()] }, REAR_12);
            const { nodes, edges } = routed(graphWithExpansion(beyond, nasExpansion(), SW_GI24));
            const sw = nodes.get(SW_01);
            const nas = nodes.get(NAS_01);

            expect(nas.x).toBe(sw.x);
            expect(nas.y).toBeGreaterThanOrEqual(sw.y + sw.height);
            expect(cable(edges, CABLE_NAS).from.x).toBe(sw.x);
            expect(cable(edges, CABLE_NAS).to.x).toBe(nas.x);
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

            expect(bounds.minX).toBe(nodes.get(PP_01).x);
            expect(bounds.maxX).toBe(nodes.get(SW_01).x + nodes.get(SW_01).width);
        });

        it('has nothing to span on an empty canvas', () => {
            expect(cablingBounds([])).toBeNull();
        });
    });
});
