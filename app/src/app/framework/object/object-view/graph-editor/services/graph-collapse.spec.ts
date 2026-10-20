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
import { of, throwError } from 'rxjs';

import { CiExplorerService } from 'src/app/framework/services/ci-explorer.service';
import { ToastService } from 'src/app/layout/toast/toast.service';

import { Connection, GraphNode } from '../interfaces/graph.interfaces';
import { ciNode, graphNode } from '../testing/graph-fixtures';
import { ConnectionTrackerService } from './connection-tracker.service';
import { GraphDataService } from './graph-data.service';
import { GraphExpansionService } from './graph-expansion.service';

/**
 * Characterization of collapse. Collapse walks outward from the node in the direction
 * it already sits - down for the root and children, up for parents - and removes
 * everything it reaches.
 */
describe('Graph collapse (characterization)', () => {
    let graphData: GraphDataService;
    let tracker: ConnectionTrackerService;
    let expansion: GraphExpansionService;
    let ci: jasmine.SpyObj<CiExplorerService>;
    let toast: jasmine.SpyObj<ToastService>;

    beforeEach(() => {
        ci = jasmine.createSpyObj<CiExplorerService>('CiExplorerService', [
            'loadWithRoot', 'expandChild', 'expandParent'
        ]);
        toast = jasmine.createSpyObj<ToastService>('ToastService', ['info', 'error', 'success']);

        graphData = new GraphDataService(ci);
        tracker = new ConnectionTrackerService();
        expansion = new GraphExpansionService(graphData, tracker, toast);
    });

    /** Registers the nodes in the instance map, which collapse walks through. */
    function register(nodes: GraphNode[]): void {
        nodes.forEach(n => graphData.getNodeInstanceMap().set(n.uid, n));
    }

    function edge(fromUid: string, toUid: string, from: number, to: number): Connection {
        return { from, to, fromLevel: 0, toLevel: 0, fromUid, toUid, isValid: true };
    }

    describe('GraphExpansionService.collapseNodeInstance', () => {
        it('removes the whole downward chain below a child node', () => {
            const root = graphNode({ id: 1, level: 0, uid: 'r' });
            const child = graphNode({ id: 2, level: 1, uid: 'c', isRoot: false, expanded: true });
            const grandchild = graphNode({ id: 3, level: 2, uid: 'g', isRoot: false });
            const nodes = [root, child, grandchild];
            const connections = [edge('r', 'c', 1, 2), edge('c', 'g', 2, 3)];
            register(nodes);

            expansion.collapseNodeInstance(child, nodes, connections);

            expect(nodes.map(n => n.uid)).toEqual(['r', 'c']);
            expect(connections.map(c => c.fromUid)).toEqual(['r']);
            expect(child.expanded).toBeFalse();
        });

        it('walks upward when collapsing a parent node', () => {
            const root = graphNode({ id: 1, level: 0, uid: 'r' });
            const parent = graphNode({ id: 2, level: -1, uid: 'p', isRoot: false, expanded: true });
            const grandparent = graphNode({ id: 3, level: -2, uid: 'gp', isRoot: false });
            const nodes = [root, parent, grandparent];
            const connections = [edge('p', 'r', 2, 1), edge('gp', 'p', 3, 2)];
            register(nodes);

            expansion.collapseNodeInstance(parent, nodes, connections);

            expect(nodes.map(n => n.uid)).toEqual(['r', 'p']);
            expect(parent.expanded).toBeFalse();
        });

        it('leaves a sibling branch untouched', () => {
            const root = graphNode({ id: 1, level: 0, uid: 'r' });
            const first = graphNode({ id: 2, level: 1, uid: 'c1', isRoot: false, expanded: true });
            const second = graphNode({ id: 3, level: 1, uid: 'c2', isRoot: false });
            const firstChild = graphNode({ id: 4, level: 2, uid: 'g1', isRoot: false });
            const nodes = [root, first, second, firstChild];
            const connections = [
                edge('r', 'c1', 1, 2),
                edge('r', 'c2', 1, 3),
                edge('c1', 'g1', 2, 4)
            ];
            register(nodes);

            expansion.collapseNodeInstance(first, nodes, connections);

            expect(nodes.map(n => n.uid)).toEqual(['r', 'c1', 'c2']);
        });

        it('does not remove a node that only sits at the same level', () => {
            const root = graphNode({ id: 1, level: 0, uid: 'r' });
            const child = graphNode({ id: 2, level: 1, uid: 'c', isRoot: false, expanded: true });
            const peer = graphNode({ id: 3, level: 1, uid: 'peer', isRoot: false });
            const nodes = [root, child, peer];
            const connections = [edge('r', 'c', 1, 2), edge('c', 'peer', 2, 3)];
            register(nodes);

            expansion.collapseNodeInstance(child, nodes, connections);

            expect(nodes.map(n => n.uid)).toEqual(['r', 'c', 'peer']);
        });
    });

    describe('expand after collapse', () => {
        /** A node is rendered under a fresh uid each time, so the edge suppression set never hides it. */
        it('brings the children back when a collapsed node is expanded again', async () => {
            const root = graphNode({ id: 1, level: 0, uid: 'r' });
            (root as any).ciNode = ciNode(1, 0);
            const nodes = [root];
            const connections: Connection[] = [];
            register(nodes);

            const child = ciNode(2, 0);
            (root.ciNode as any).direction = 'child';
            ci.expandChild.and.returnValue(of({ child_nodes: [child], child_edges: [] } as any));

            await expansion.expandNodeInstance(root, root.ciNode!, nodes, connections, [], [],
                new Map<string, { icon: string; gradient: string }>());
            expect(nodes.length).toBe(2);
            register(nodes);

            expansion.collapseNodeInstance(root, nodes, connections);
            expect(nodes.map(n => n.uid)).toEqual(['r']);

            await expansion.expandNodeInstance(root, root.ciNode!, nodes, connections, [], [],
                new Map<string, { icon: string; gradient: string }>());

            expect(nodes.length).toBe(2);
            expect(connections.length).toBe(1);
        });

        it('names both endpoints of the edge it adds', async () => {
            const root = graphNode({ id: 1, level: 0, uid: 'r' });
            (root as any).ciNode = ciNode(1, 0);
            (root.ciNode as any).direction = 'child';
            const nodes = [root];
            const connections: Connection[] = [];
            register(nodes);

            ci.expandChild.and.returnValue(of({ child_nodes: [ciNode(2, 0)], child_edges: [] } as any));

            await expansion.expandNodeInstance(root, root.ciNode!, nodes, connections, [], [],
                new Map<string, { icon: string; gradient: string }>());

            expect(connections[0].from).toBe(1);
            expect(connections[0].to).toBe(2);
        });

        it('tells the user when an expansion fails instead of silently closing', async () => {
            const root = graphNode({ id: 1, level: 0, uid: 'r' });
            (root as any).ciNode = ciNode(1, 0);
            (root.ciNode as any).direction = 'child';
            register([root]);

            ci.expandChild.and.returnValue(throwError(() => ({ error: { message: 'Backend is down' } })));

            await expansion.expandNodeInstance(root, root.ciNode!, [root], [], [], [],
                new Map<string, { icon: string; gradient: string }>());

            expect(toast.error).toHaveBeenCalledWith('Backend is down');
            expect(root.expanded).toBeFalse();
        });
    });

    describe('expansion bookkeeping', () => {
        it('tracks and forgets which CIs are expanded', () => {
            graphData.addExpandedNode(1);
            expect(graphData.getExpandedNodes().has(1)).toBeTrue();

            graphData.removeExpandedNode(1);
            expect(graphData.getExpandedNodes().has(1)).toBeFalse();
        });

        it('remembers the raw CI behind a rendered node', () => {
            const nodes: GraphNode[] = [];
            graphData.mergeNodes(nodes, [ciNode(7, 0, { title: 'db-01' })], new Map());

            expect(graphData.getCINode(7)!.title).toBe('db-01');
        });
    });
});
