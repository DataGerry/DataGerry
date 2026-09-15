/*
* DATAGERRY - OpenSource Enterprise CMDB
* Copyright (C) 2026 becon GmbH
*
* This program is free software: you can redistribute it and/or modify
* it under the terms of the GNU Affero General Public License as
* published by the Free Software Foundation, either version 3 of the
* License, or (at your option) any later version.
*
* You should have received a copy of the GNU Affero General Public License
* along with this program. If not, see <https://www.gnu.org/licenses/>.
*/
import { TestBed } from '@angular/core/testing';
import { of } from 'rxjs';

import { LoaderService } from 'src/app/core/services/loader.service';
import { CiExplorerService } from 'src/app/framework/services/ci-explorer.service';
import { ToastService } from 'src/app/layout/toast/toast.service';

import { ciEdge, ciNode, graphNode, graphResponse } from '../testing/graph-fixtures';
import { ConnectionTrackerService } from './connection-tracker.service';
import { GraphDataService } from './graph-data.service';
import { GraphEditorStore } from './graph-editor.store';
import { GraphExpansionService } from './graph-expansion.service';
import { GraphLayoutService } from './layout/graph-layout.service';

/**
 * Carries over the graph-ingest assertions from the component spec. The duplicate-instance
 * rule is the subtlest behaviour in the feature and the easiest to lose in a rewrite.
 */
describe('GraphEditorStore (characterization)', () => {
    let store: GraphEditorStore;
    let graphData: GraphDataService;
    let toast: jasmine.SpyObj<ToastService>;

    beforeEach(() => {
        const ci = jasmine.createSpyObj<CiExplorerService>('CiExplorerService', [
            'loadWithRoot', 'expandChild', 'expandParent'
        ]);
        ci.loadWithRoot.and.returnValue(of(graphResponse()));
        toast = jasmine.createSpyObj<ToastService>('ToastService', ['info', 'error', 'success']);

        TestBed.configureTestingModule({
            providers: [
                GraphEditorStore,
                GraphDataService,
                GraphLayoutService,
                GraphExpansionService,
                ConnectionTrackerService,
                { provide: CiExplorerService, useValue: ci },
                { provide: ToastService, useValue: toast },
                {
                    provide: LoaderService,
                    useValue: jasmine.createSpyObj<LoaderService>('LoaderService', ['show', 'hide'], {
                        isLoading$: of(false)
                    })
                }
            ]
        });

        store = TestBed.inject(GraphEditorStore);
        graphData = TestBed.inject(GraphDataService);
    });

    describe('paint', () => {
        it('marks the root at level 0', () => {
            store.paint(graphResponse({ root_node: ciNode(1, 0) }));

            expect(store.nodes.length).toBe(1);
            expect(store.nodes[0].id).toBe(1);
            expect(store.nodes[0].level).toBe(0);
            expect(store.nodes[0].isRoot).toBeTrue();
        });

        it('puts parents above the root and children below it', () => {
            store.paint(graphResponse({
                root_node: ciNode(1, 0),
                parent_nodes: [ciNode(2, 0)],
                child_nodes: [ciNode(3, 0)]
            }));

            const byId = new Map(store.nodes.map(n => [n.id, n]));
            expect(byId.get(2)!.level).toBe(-1);
            expect(byId.get(3)!.level).toBe(1);
        });

        it('renders a CI that is both a parent and a child as two separate instances', () => {
            store.paint(graphResponse({
                root_node: ciNode(1, 0),
                parent_nodes: [ciNode(5, 0)],
                child_nodes: [ciNode(5, 0)]
            }));

            const instances = store.nodes.filter(n => n.id === 5);

            expect(instances.length).toBe(2);
            expect(instances.map(n => n.level).sort()).toEqual([-1, 1]);
            expect(instances[0].uid).not.toBe(instances[1].uid);
        });

        it('de-duplicates a CI that appears twice on the same side', () => {
            store.paint(graphResponse({
                root_node: ciNode(1, 0),
                parent_nodes: [ciNode(2, 0), ciNode(2, 0)]
            }));

            expect(store.nodes.filter(n => n.id === 2).length).toBe(1);
        });

        it('marks the root as expanded so it can be collapsed again', () => {
            store.paint(graphResponse({ root_node: ciNode(1, 0) }));

            expect(graphData.getExpandedNodes().has(1)).toBeTrue();
        });

        it('builds connections from both the parent and the child edge lists', () => {
            store.paint(graphResponse({
                root_node: ciNode(1, 0),
                parent_nodes: [ciNode(2, 0)],
                child_nodes: [ciNode(3, 0)],
                parent_edges: [ciEdge(2, 1)],
                child_edges: [ciEdge(1, 3)]
            }));

            expect(store.connections.length).toBe(2);
            expect(store.connections.every(c => c.isValid)).toBeTrue();
        });

        it('clears the previous graph before painting a new one', () => {
            store.paint(graphResponse({ root_node: ciNode(1, 0), child_nodes: [ciNode(3, 0)] }));
            store.paint(graphResponse({ root_node: ciNode(9, 0) }));

            expect(store.nodes.length).toBe(1);
            expect(store.nodes[0].id).toBe(9);
        });

        it('lays the nodes out, so nothing is left stacked at the origin', () => {
            store.paint(graphResponse({
                root_node: ciNode(1, 0),
                child_nodes: [ciNode(2, 0), ciNode(3, 0)],
                child_edges: [ciEdge(1, 2), ciEdge(1, 3)]
            }));

            const children = store.nodes.filter(n => n.level === 1);
            expect(children.length).toBe(2);
            expect(children[0].x).not.toBe(children[1].x);
        });

        it('warns once a level comes back at the server limit', () => {
            store.paint(graphResponse({
                root_node: ciNode(1, 0),
                child_nodes: Array.from({ length: 20 }, (_, i) => ciNode(i + 2, 0))
            }));

            expect(toast.info).toHaveBeenCalled();
        });
    });

    describe('derived collections', () => {
        it('exposes the painted graph through the visible signals', () => {
            store.paint(graphResponse({
                root_node: ciNode(1, 0),
                child_nodes: [ciNode(2, 0)],
                child_edges: [ciEdge(1, 2)]
            }));

            expect(store.visibleNodes().map(n => n.id)).toEqual([1, 2]);
            expect(store.visibleConnections().length).toBe(1);
            expect(store.nodeCount()).toBe(2);
        });

        it('returns the same array instance until the graph changes', () => {
            store.paint(graphResponse({ root_node: ciNode(1, 0) }));

            const first = store.visibleNodes();
            expect(store.visibleNodes()).toBe(first);

            store.paint(graphResponse({ root_node: ciNode(2, 0) }));
            expect(store.visibleNodes()).not.toBe(first);
        });

        it('has nothing to show before anything is painted', () => {
            expect(store.visibleNodes()).toEqual([]);
            expect(store.visibleConnections()).toEqual([]);
        });
    });

    describe('updateNodeStates', () => {
        it('counts a lower-level neighbour as a parent and a higher-level one as a child', () => {
            const parent = graphNode({ id: 1, level: -1, uid: 'p', isRoot: false });
            const root = graphNode({ id: 2, level: 0, uid: 'r' });
            const child = graphNode({ id: 3, level: 1, uid: 'c', isRoot: false });
            store.nodes = [parent, root, child];
            store.connections = [
                { from: 1, to: 2, fromLevel: -1, toLevel: 0, fromUid: 'p', toUid: 'r', isValid: true },
                { from: 2, to: 3, fromLevel: 0, toLevel: 1, fromUid: 'r', toUid: 'c', isValid: true }
            ];
            spyOn(graphData, 'getNodeInstanceMap').and.returnValue(
                new Map([['p', parent], ['r', root], ['c', child]])
            );

            store.updateNodeStates();

            expect(root.connectionCount).toEqual({ parents: 1, children: 1 });
            expect(root.hasParents).toBeTrue();
            expect(root.hasChildren).toBeTrue();
            expect(parent.connectionCount).toEqual({ parents: 0, children: 1 });
            expect(child.connectionCount).toEqual({ parents: 1, children: 0 });
        });

        it('ignores connections that are not valid', () => {
            const root = graphNode({ id: 1, level: 0, uid: 'r' });
            const child = graphNode({ id: 2, level: 1, uid: 'c', isRoot: false });
            store.nodes = [root, child];
            store.connections = [
                { from: 1, to: 2, fromLevel: 0, toLevel: 1, fromUid: 'r', toUid: 'c', isValid: false }
            ];
            spyOn(graphData, 'getNodeInstanceMap').and.returnValue(new Map([['r', root], ['c', child]]));

            store.updateNodeStates();

            expect(root.connectionCount).toEqual({ parents: 0, children: 0 });
            expect(root.hasChildren).toBeFalse();
        });
    });

    describe('selection', () => {
        it('clears the node, the multi-selection and the connection together', () => {
            store.selectedNode = graphNode({ id: 1, level: 0 });
            store.selectedNodes = new Set([1, 2]);
            store.selectedConnection = { from: 1, to: 2, fromLevel: 0, toLevel: 1 };

            store.clearSelection();

            expect(store.selectedNode).toBeNull();
            expect(store.selectedNodes.size).toBe(0);
            expect(store.selectedConnection).toBeNull();
        });

        it('selecting a connection drops any node selection', () => {
            store.selectedNode = graphNode({ id: 1, level: 0 });
            store.selectedNodes = new Set([1]);

            store.selectConnection({ from: 1, to: 2, fromLevel: 0, toLevel: 1 });

            expect(store.selectedNode).toBeNull();
            expect(store.selectedNodes.size).toBe(0);
            expect(store.selectedConnection).not.toBeNull();
        });

        it('replaces the selection unless the caller asks to add to it', () => {
            const first = graphNode({ id: 1, level: 0, uid: 'a' });
            const second = graphNode({ id: 2, level: 1, uid: 'b', isRoot: false });

            store.select(first);
            store.select(second);
            expect(store.selectedNodes.size).toBe(1);

            store.select(first, true);
            expect(store.selectedNodes.size).toBe(2);
        });

        it('toggles a node in and out of the selection', () => {
            const node = graphNode({ id: 1, level: 0 });

            store.toggleNodeSelection(node);
            expect(store.selectedNodes.has(1)).toBeTrue();
            expect(store.selectedNode).toBe(node);

            store.toggleNodeSelection(node);
            expect(store.selectedNodes.has(1)).toBeFalse();
            expect(store.selectedNode).toBeNull();
        });
    });

    describe('expand affordances', () => {
        it('labels the root by whether anything else is on screen', () => {
            const root = graphNode({ id: 1, level: 0, uid: 'r' });
            const child = graphNode({ id: 2, level: 1, uid: 'c', isRoot: false });

            store.nodes = [root];
            expect(store.expandLabel(root)).toBe('Expand');
            expect(store.expandIcon(root)).toBe('unfold_more');

            store.nodes = [root, child];
            expect(store.expandLabel(root)).toBe('Collapse');
            expect(store.expandIcon(root)).toBe('unfold_less');
        });

        it('labels a normal node by its own expanded flag', () => {
            const open = graphNode({ id: 2, level: 1, uid: 'c', isRoot: false, expanded: true });
            const shut = graphNode({ id: 3, level: 1, uid: 'd', isRoot: false, expanded: false });

            expect(store.expandLabel(open)).toBe('Collapse');
            expect(store.expandLabel(shut)).toBe('Expand');
        });

        it('falls back to Expand when nothing is selected', () => {
            expect(store.expandLabel(null)).toBe('Expand');
            expect(store.expandIcon(null)).toBe('unfold_more');
        });
    });

    describe('performanceHint', () => {
        it('stays empty until the graph is large', () => {
            store.nodes = Array.from({ length: 500 }, (_, i) => graphNode({ id: i, uid: `n${i}` }));
            expect(store.performanceHint()).toBe('');

            store.nodes.push(graphNode({ id: 501, uid: 'n501' }));
            expect(store.performanceHint()).toContain('501 nodes');
        });
    });
});
