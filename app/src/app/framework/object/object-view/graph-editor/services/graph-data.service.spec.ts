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

* You should have received a copy of the GNU Affero General Public License
* along with this program. If not, see <https://www.gnu.org/licenses/>.
*/
import { CiExplorerService } from 'src/app/framework/services/ci-explorer.service';

import { Connection, GraphNode } from '../interfaces/graph.interfaces';
import { ciEdge, ciNode, linkedObject, relationMeta, typeInfo } from '../testing/graph-fixtures';
import { GraphDataService } from './graph-data.service';

/**
 * Characterization of node/edge ingest. The duplicate-instance rule and the
 * parent-to-child edge direction are the subtlest behaviours in the feature.
 */
describe('GraphDataService (characterization)', () => {
    let service: GraphDataService;

    beforeEach(() => {
        const ci = jasmine.createSpyObj<CiExplorerService>('CiExplorerService', [
            'loadWithRoot',
            'expandChild',
            'expandParent'
        ]);
        service = new GraphDataService(ci);
    });

    describe('extractLabel', () => {
        it('reports a null title as unset', () => {
            expect(service.extractLabel(ciNode(1, 0, { title: null as unknown as string })))
                .toBe('Label not selected');
        });

        it('reports an empty title as empty', () => {
            expect(service.extractLabel(ciNode(1, 0, { title: '' }))).toBe('Label is empty');
        });

        it('passes a real title through', () => {
            expect(service.extractLabel(ciNode(1, 0, { title: 'web-01' }))).toBe('web-01');
        });
    });

    describe('getNodes / getEdges', () => {
        it('accepts both the child_ and children_ response spellings', () => {
            expect(service.getNodes({ child_nodes: [ciNode(2, 1)] } as never, 'child').length).toBe(1);
            expect(service.getNodes({ children_nodes: [ciNode(2, 1)] } as never, 'child').length).toBe(1);
            expect(service.getEdges({ child_edges: [ciEdge(1, 2)] } as never, 'child').length).toBe(1);
            expect(service.getEdges({ children_edges: [ciEdge(1, 2)] } as never, 'child').length).toBe(1);
        });

        it('falls back to an empty list when the key is absent', () => {
            expect(service.getNodes({} as never, 'parent')).toEqual([]);
            expect(service.getEdges({} as never, 'parent')).toEqual([]);
        });
    });

    describe('generateTrueUniqueUid', () => {
        it('never repeats a uid, even for the same id and level', () => {
            const first = service.generateTrueUniqueUid(1, 0);
            const second = service.generateTrueUniqueUid(1, 0);

            expect(first).not.toBe(second);
            expect(first.endsWith('_1_L0')).toBeTrue();
        });
    });

    describe('mergeNodes', () => {
        it('builds a UI node per CI and registers it in the instance map', () => {
            const nodes: GraphNode[] = [];
            const configs = new Map<string, { icon: string; gradient: string }>();

            service.mergeNodes(nodes, [ciNode(1, 0, { title: 'web-01' })], configs);

            expect(nodes.length).toBe(1);
            expect(nodes[0].id).toBe(1);
            expect(nodes[0].label).toBe('web-01');
            expect(nodes[0].type).toBe('Server');
            expect(nodes[0].x).toBe(0);
            expect(nodes[0].y).toBe(0);
            expect(service.getNodeInstanceMap().get(nodes[0].uid)).toBe(nodes[0]);
        });

        it('optimistically marks every new node as having both parents and children', () => {
            const nodes: GraphNode[] = [];
            service.mergeNodes(nodes, [ciNode(1, 0)], new Map());

            expect(nodes[0].hasParents).toBeTrue();
            expect(nodes[0].hasChildren).toBeTrue();
        });

        it('records the first icon and colour seen for a type and does not overwrite it', () => {
            const configs = new Map<string, { icon: string; gradient: string }>();
            const first = ciNode(1, 0, { type_info: typeInfo({ label: 'Server', icon: 'icon-a', type_color: '#111' }) });
            const second = ciNode(2, 1, { type_info: typeInfo({ label: 'Server', icon: 'icon-b', type_color: '#222' }) });

            service.mergeNodes([], [first, second], configs);

            expect(configs.get('Server')).toEqual({ icon: 'icon-a', gradient: '#111' });
        });

        it('derives status from the linked object active flag', () => {
            const nodes: GraphNode[] = [];
            service.mergeNodes(
                nodes,
                [
                    ciNode(1, 0, { linked_object: linkedObject({ public_id: 1, active: true }) }),
                    ciNode(2, 1, { linked_object: linkedObject({ public_id: 2, active: false }) })
                ],
                new Map()
            );

            expect(nodes.map(n => n.status)).toEqual(['active', 'inactive']);
        });

        it('gives the same CI a distinct instance per level', () => {
            const nodes: GraphNode[] = [];
            service.mergeNodes(nodes, [ciNode(5, -1), ciNode(5, 1)], new Map());

            expect(nodes.length).toBe(2);
            expect(nodes[0].uid).not.toBe(nodes[1].uid);
            expect(nodes.map(n => n.level)).toEqual([-1, 1]);
        });
    });

    describe('mergeEdges', () => {
        /** mergeEdges matches CIs by id, so the nodes must already be in the array. */
        function seed(cis: Parameters<GraphDataService['mergeNodes']>[1]): GraphNode[] {
            const nodes: GraphNode[] = [];
            service.mergeNodes(nodes, cis, new Map());
            return nodes;
        }

        it('connects a parent level to the adjacent child level', () => {
            const nodes = seed([ciNode(1, 0), ciNode(2, 1)]);
            const connections: Connection[] = [];

            service.mergeEdges(connections, nodes, [ciEdge(1, 2)]);

            expect(connections.length).toBe(1);
            expect(connections[0].from).toBe(1);
            expect(connections[0].to).toBe(2);
            expect(connections[0].isValid).toBeTrue();
        });

        it('drops an edge that points from a child up to its parent', () => {
            // node 2 sits at level 1, node 1 at level 0, and the edge runs 2 -> 1.
            const nodes = seed([ciNode(1, 0), ciNode(2, 1)]);
            const connections: Connection[] = [];

            service.mergeEdges(connections, nodes, [ciEdge(2, 1)]);

            expect(connections).toEqual([]);
        });

        it('drops an edge between levels that are not adjacent', () => {
            const nodes = seed([ciNode(1, 0), ciNode(2, 2)]);
            const connections: Connection[] = [];

            service.mergeEdges(connections, nodes, [ciEdge(1, 2)]);

            expect(connections).toEqual([]);
        });

        it('carries the first relation entry onto the connection', () => {
            const nodes = seed([ciNode(1, 0), ciNode(2, 1)]);
            const connections: Connection[] = [];
            const meta = relationMeta({ relation_label: 'Hosts', relation_color: '#abc', relation_icon: 'fas fa-cube' });

            service.mergeEdges(connections, nodes, [ciEdge(1, 2, [meta, relationMeta({ relation_label: 'Ignored' })])]);

            expect(connections[0].relationLabel).toBe('Hosts');
            expect(connections[0].relationColor).toBe('#abc');
            expect(connections[0].relationIcon).toBe('fas fa-cube');
        });

        it('marks an undirected edge, so the canvas can drop its arrow head', () => {
            const nodes = seed([ciNode(1, 0), ciNode(2, 1)]);
            const connections: Connection[] = [];
            const meta = relationMeta({ source: 'port_connection', undirected: true });

            service.mergeEdges(connections, nodes, [ciEdge(1, 2, [meta])]);

            expect(connections[0].undirected).toBeTrue();
        });

        it('leaves a plain relation edge directed', () => {
            const nodes = seed([ciNode(1, 0), ciNode(2, 1)]);
            const connections: Connection[] = [];

            service.mergeEdges(connections, nodes, [ciEdge(1, 2)]);

            expect(connections[0].undirected).toBeFalse();
        });

        it('creates one connection per rendered instance pair', () => {
            // CI 2 exists at level -1 and level 1; only the level-1 copy is adjacent below the root.
            const nodes = seed([ciNode(1, 0), ciNode(2, 1), ciNode(2, -1)]);
            const connections: Connection[] = [];

            service.mergeEdges(connections, nodes, [ciEdge(1, 2)]);

            expect(connections.length).toBe(1);
            expect(connections[0].toLevel).toBe(1);
        });

        it('ignores a repeated edge between the same two instances', () => {
            const nodes = seed([ciNode(1, 0), ciNode(2, 1)]);
            const connections: Connection[] = [];

            service.mergeEdges(connections, nodes, [ciEdge(1, 2), ciEdge(1, 2)]);

            expect(connections.length).toBe(1);
        });

        it('adds nothing at all while backend edges are suppressed', () => {
            const nodes = seed([ciNode(1, 0), ciNode(2, 1)]);
            const connections: Connection[] = [];
            service.setSkipBackendEdges(true);

            service.mergeEdges(connections, nodes, [ciEdge(1, 2)]);

            expect(connections).toEqual([]);
        });
    });

    describe('edge index', () => {
        it('returns every stored edge between a pair of CIs', () => {
            service.storeAndIndexEdge(ciEdge(1, 2));
            service.storeAndIndexEdge(ciEdge(1, 2, [relationMeta({ relation_id: 200 })]));

            expect(service.getAllEdgesBetween(1, 2).length).toBe(2);
            expect(service.getAllEdgesBetween(2, 1)).toEqual([]);
        });

        it('forgets everything once the graph is cleared', () => {
            service.storeAndIndexEdge(ciEdge(1, 2));
            service.addExpandedNode(1);

            service.clearAllData();

            expect(service.getAllEdgesBetween(1, 2)).toEqual([]);
            expect(service.getExpandedNodes().size).toBe(0);
            expect(service.getNodeInstanceMap().size).toBe(0);
        });
    });

    describe('removeNodeInstancesByUID', () => {
        it('removes the named instances and every connection touching them', () => {
            const nodes: GraphNode[] = [];
            service.mergeNodes(nodes, [ciNode(1, 0), ciNode(2, 1), ciNode(3, 1)], new Map());
            const [root, child, other] = nodes;
            const connections: Connection[] = [
                { from: 1, to: 2, fromLevel: 0, toLevel: 1, fromUid: root.uid, toUid: child.uid, isValid: true },
                { from: 1, to: 3, fromLevel: 0, toLevel: 1, fromUid: root.uid, toUid: other.uid, isValid: true }
            ];

            service.removeNodeInstancesByUID(nodes, connections, [child.uid]);

            expect(nodes.map(n => n.id)).toEqual([1, 3]);
            expect(connections.length).toBe(1);
            expect(connections[0].to).toBe(3);
            expect(service.getNodeInstanceMap().has(child.uid)).toBeFalse();
        });

        it('removes only the instance named, not its twin at another level', () => {
            const nodes: GraphNode[] = [];
            service.mergeNodes(nodes, [ciNode(1, 0), ciNode(5, -1), ciNode(5, 1)], new Map());
            const asChild = nodes[2];

            service.removeNodeInstancesByUID(nodes, [], [asChild.uid]);

            expect(nodes.map(n => n.level)).toEqual([0, -1]);
        });
    });
});
