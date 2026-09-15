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
import { TestBed } from '@angular/core/testing';
import { ReactiveFormsModule } from '@angular/forms';
import { NgbModal } from '@ng-bootstrap/ng-bootstrap';
import { of } from 'rxjs';

import { LoaderService } from 'src/app/core/services/loader.service';
import { FullscreenModalService } from 'src/app/core/services/fullscreen-modal.service';
import { CiExplorerService } from 'src/app/framework/services/ci-explorer.service';
import { RelationService } from 'src/app/framework/services/relaion.service';
import { TypeService } from 'src/app/framework/services/type.service';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { PermissionService } from 'src/app/modules/auth/services/permission.service';

import { GraphEditorComponent } from './graph-editor.component';
import { GraphDataService } from './services/graph-data.service';
import { GraphProfileService } from './services/graph-profile.service';
import { CiExplorerExportService } from './services/ci-explorer-export.service';
import { ciEdge, ciNode, graphNode, graphResponse } from './testing/graph-fixtures';
import { Connection } from './interfaces/graph.interfaces';

/**
 * Characterization of the graph ingest. The duplicate-instance rule below is the
 * subtlest behaviour in the feature and the easiest to lose in a rewrite.
 *
 * `ngOnInit` is deliberately never run: it starts a permanent requestAnimationFrame
 * loop and fires two API calls that have nothing to do with these assertions.
 */
describe('GraphEditorComponent (characterization)', () => {
    let component: GraphEditorComponent;
    let graphData: GraphDataService;

    beforeEach(() => {
        const ci = jasmine.createSpyObj<CiExplorerService>('CiExplorerService', [
            'loadWithRoot', 'expandChild', 'expandParent'
        ]);
        ci.loadWithRoot.and.returnValue(of(graphResponse()));

        const permission = jasmine.createSpyObj<PermissionService>('PermissionService', [
            'hasRight', 'hasExtendedRight'
        ]);
        permission.hasRight.and.returnValue(true);
        permission.hasExtendedRight.and.returnValue(true);

        TestBed.configureTestingModule({
            imports: [ReactiveFormsModule],
            declarations: [GraphEditorComponent],
            providers: [
                { provide: CiExplorerService, useValue: ci },
                { provide: PermissionService, useValue: permission },
                {
                    provide: LoaderService,
                    useValue: jasmine.createSpyObj<LoaderService>('LoaderService', ['show', 'hide'], {
                        isLoading$: of(false)
                    })
                },
                {
                    provide: ToastService,
                    useValue: jasmine.createSpyObj<ToastService>('ToastService', ['info', 'error', 'success'])
                },
                {
                    provide: TypeService,
                    useValue: jasmine.createSpyObj<TypeService>('TypeService', ['getTypes'])
                },
                {
                    provide: RelationService,
                    useValue: jasmine.createSpyObj<RelationService>('RelationService', ['getRelations'])
                },
                {
                    provide: GraphProfileService,
                    useValue: jasmine.createSpyObj<GraphProfileService>('GraphProfileService', [
                        'getProfiles', 'loadFilterOptions', 'applyProfile', 'hasActiveFilters',
                        'openProfileManager', 'saveCurrentFiltersAsProfile'
                    ])
                },
                {
                    provide: CiExplorerExportService,
                    useValue: jasmine.createSpyObj<CiExplorerExportService>('CiExplorerExportService', [
                        'exportGraphAsImage'
                    ])
                },
                { provide: NgbModal, useValue: jasmine.createSpyObj<NgbModal>('NgbModal', ['open']) },
                {
                    provide: FullscreenModalService,
                    useValue: jasmine.createSpyObj<FullscreenModalService>('FullscreenModalService', ['open'])
                }
            ]
        }).overrideComponent(GraphEditorComponent, { set: { template: '' } });

        const fixture = TestBed.createComponent(GraphEditorComponent);
        component = fixture.componentInstance;
        graphData = fixture.debugElement.injector.get(GraphDataService);
    });

    /** Invokes the private ingest routine without standing up the template. */
    function paint(response: Parameters<GraphEditorComponent['ngOnChanges']>[0] extends never ? never : any): void {
        (component as unknown as { paintInitial: (r: unknown) => void }).paintInitial(response);
    }

    describe('paintInitial', () => {
        it('marks the root at level 0', () => {
            paint(graphResponse({ root_node: ciNode(1, 0) }));

            expect(component.nodes.length).toBe(1);
            expect(component.nodes[0].id).toBe(1);
            expect(component.nodes[0].level).toBe(0);
            expect(component.nodes[0].isRoot).toBeTrue();
        });

        it('puts parents above the root and children below it', () => {
            paint(graphResponse({
                root_node: ciNode(1, 0),
                parent_nodes: [ciNode(2, 0)],
                child_nodes: [ciNode(3, 0)]
            }));

            const byId = new Map(component.nodes.map(n => [n.id, n]));
            expect(byId.get(2)!.level).toBe(-1);
            expect(byId.get(3)!.level).toBe(1);
        });

        it('renders a CI that is both a parent and a child as two separate instances', () => {
            paint(graphResponse({
                root_node: ciNode(1, 0),
                parent_nodes: [ciNode(5, 0)],
                child_nodes: [ciNode(5, 0)]
            }));

            const instances = component.nodes.filter(n => n.id === 5);

            expect(instances.length).toBe(2);
            expect(instances.map(n => n.level).sort()).toEqual([-1, 1]);
            expect(instances[0].uid).not.toBe(instances[1].uid);
        });

        it('de-duplicates a CI that appears twice on the same side', () => {
            paint(graphResponse({
                root_node: ciNode(1, 0),
                parent_nodes: [ciNode(2, 0), ciNode(2, 0)]
            }));

            expect(component.nodes.filter(n => n.id === 2).length).toBe(1);
        });

        it('marks the root as expanded so it can be collapsed again', () => {
            paint(graphResponse({ root_node: ciNode(1, 0) }));

            expect(graphData.getExpandedNodes().has(1)).toBeTrue();
        });

        it('builds connections from both the parent and the child edge lists', () => {
            paint(graphResponse({
                root_node: ciNode(1, 0),
                parent_nodes: [ciNode(2, 0)],
                child_nodes: [ciNode(3, 0)],
                parent_edges: [ciEdge(2, 1)],
                child_edges: [ciEdge(1, 3)]
            }));

            expect(component.connections.length).toBe(2);
            expect(component.connections.every(c => c.isValid)).toBeTrue();
        });

        it('clears the previous graph before painting a new one', () => {
            paint(graphResponse({ root_node: ciNode(1, 0), child_nodes: [ciNode(3, 0)] }));
            paint(graphResponse({ root_node: ciNode(9, 0) }));

            expect(component.nodes.length).toBe(1);
            expect(component.nodes[0].id).toBe(9);
        });

        it('lays the nodes out, so nothing is left stacked at the origin', () => {
            paint(graphResponse({
                root_node: ciNode(1, 0),
                child_nodes: [ciNode(2, 0), ciNode(3, 0)],
                child_edges: [ciEdge(1, 2), ciEdge(1, 3)]
            }));

            const children = component.nodes.filter(n => n.level === 1);
            expect(children.length).toBe(2);
            expect(children[0].x).not.toBe(children[1].x);
        });
    });

    describe('updateNodeStates', () => {
        /** Counts are derived from the level of the node at the other end of each edge. */
        function countStates(): void {
            (component as unknown as { updateNodeStates: () => void }).updateNodeStates();
        }

        it('counts a lower-level neighbour as a parent and a higher-level one as a child', () => {
            const parent = graphNode({ id: 1, level: -1, uid: 'p', isRoot: false });
            const root = graphNode({ id: 2, level: 0, uid: 'r' });
            const child = graphNode({ id: 3, level: 1, uid: 'c', isRoot: false });
            component.nodes = [parent, root, child];
            component.connections = [
                { from: 1, to: 2, fromLevel: -1, toLevel: 0, fromUid: 'p', toUid: 'r', isValid: true },
                { from: 2, to: 3, fromLevel: 0, toLevel: 1, fromUid: 'r', toUid: 'c', isValid: true }
            ];
            spyOn(graphData, 'getNodeInstanceMap').and.returnValue(
                new Map([['p', parent], ['r', root], ['c', child]])
            );

            countStates();

            expect(root.connectionCount).toEqual({ parents: 1, children: 1 });
            expect(root.hasParents).toBeTrue();
            expect(root.hasChildren).toBeTrue();
            expect(parent.connectionCount).toEqual({ parents: 0, children: 1 });
            expect(child.connectionCount).toEqual({ parents: 1, children: 0 });
        });

        it('ignores connections that are not valid', () => {
            const root = graphNode({ id: 1, level: 0, uid: 'r' });
            const child = graphNode({ id: 2, level: 1, uid: 'c', isRoot: false });
            component.nodes = [root, child];
            component.connections = [
                { from: 1, to: 2, fromLevel: 0, toLevel: 1, fromUid: 'r', toUid: 'c', isValid: false } as Connection
            ];
            spyOn(graphData, 'getNodeInstanceMap').and.returnValue(new Map([['r', root], ['c', child]]));

            countStates();

            expect(root.connectionCount).toEqual({ parents: 0, children: 0 });
            expect(root.hasChildren).toBeFalse();
        });
    });

    describe('selection', () => {
        it('clears the node, the multi-selection and the connection together', () => {
            component.selectedNode = graphNode({ id: 1, level: 0 });
            component.selectedNodes = new Set([1, 2]);
            component.selectedConnection = { from: 1, to: 2, fromLevel: 0, toLevel: 1 };

            component.clearSelection();

            expect(component.selectedNode).toBeNull();
            expect(component.selectedNodes.size).toBe(0);
            expect(component.selectedConnection).toBeNull();
        });

        it('selecting a connection drops any node selection', () => {
            component.selectedNode = graphNode({ id: 1, level: 0 });
            component.selectedNodes = new Set([1]);

            component.selectConnection({ from: 1, to: 2, fromLevel: 0, toLevel: 1 });

            expect(component.selectedNode).toBeNull();
            expect(component.selectedNodes.size).toBe(0);
            expect(component.selectedConnection).not.toBeNull();
        });
    });
});
