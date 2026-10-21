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
import { ElementRef } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { of } from 'rxjs';

import { LoaderService } from 'src/app/core/services/loader.service';
import { CiExplorerService } from 'src/app/framework/services/ci-explorer.service';
import { ToastService } from 'src/app/layout/toast/toast.service';

import { LAYOUT_CONFIG } from '../constants/graph.constants';
import { ciEdge, ciNode, graphResponse } from '../testing/graph-fixtures';
import { ConnectionTrackerService } from './connection-tracker.service';
import { GraphDataService } from './graph-data.service';
import { GraphEditorStore } from './graph-editor.store';
import { GraphExpansionService } from './graph-expansion.service';
import { GraphViewportService } from './graph-viewport.service';
import { GraphLayoutService } from './layout/graph-layout.service';

/**
 * Opening the graph view has to land the graph in the middle of the canvas. The shell wires
 * that to the store's paint callback, so this drives the real store, the real layout and the
 * real viewport service against a real sized element and checks where the nodes end up.
 */
describe('Centring a freshly painted graph (in-browser)', () => {
    let store: GraphEditorStore;
    let viewport: GraphViewportService;
    let host: HTMLElement;
    let container: ElementRef;

    const WIDTH = 1200;
    const HEIGHT = 800;

    beforeEach(() => {
        const ci = jasmine.createSpyObj<CiExplorerService>('CiExplorerService', [
            'loadWithRoot', 'expandChild', 'expandParent'
        ]);
        ci.loadWithRoot.and.returnValue(of(graphResponse()));

        TestBed.configureTestingModule({
            providers: [
                GraphEditorStore, GraphDataService, GraphLayoutService,
                GraphExpansionService, ConnectionTrackerService, GraphViewportService,
                { provide: CiExplorerService, useValue: ci },
                { provide: ToastService, useValue: jasmine.createSpyObj<ToastService>('ToastService', ['info', 'error', 'success']) },
                {
                    provide: LoaderService,
                    useValue: jasmine.createSpyObj<LoaderService>('LoaderService', ['show', 'hide'], { isLoading$: of(false) })
                }
            ]
        });

        store = TestBed.inject(GraphEditorStore);
        viewport = TestBed.inject(GraphViewportService);

        // A real element, so the service measures a real rect exactly as it does in the app.
        host = document.createElement('div');
        host.style.cssText = `position:absolute;left:0;top:0;width:${WIDTH}px;height:${HEIGHT}px`;
        document.body.appendChild(host);
        container = new ElementRef(host);

        // This is the wiring the shell sets up in ngOnInit.
        store.setPaintedCallback(() => viewport.centerViewport(container, store.nodes));
    });

    afterEach(() => host.remove());

    /** Where a node's centre lands on screen once the canvas transform is applied. */
    function screenCentre() {
        const zoom = viewport.getZoom();
        const xs = store.nodes.map(n => n.x);
        const ys = store.nodes.map(n => n.y);
        const minX = Math.min(...xs);
        const maxX = Math.max(...xs) + LAYOUT_CONFIG.nodeWidth;
        const minY = Math.min(...ys);
        const maxY = Math.max(...ys) + LAYOUT_CONFIG.nodeHeight;

        return {
            x: ((minX + maxX) / 2) * zoom + viewport.getViewportX(),
            y: ((minY + maxY) / 2) * zoom + viewport.getViewportY()
        };
    }

    function paintTree() {
        store.paint(graphResponse({
            root_node: ciNode(1, 0),
            parent_nodes: [ciNode(2, 0)],
            child_nodes: [ciNode(3, 0), ciNode(4, 0)],
            parent_edges: [ciEdge(2, 1)],
            child_edges: [ciEdge(1, 3), ciEdge(1, 4)]
        }));
    }

    it('leaves the viewport at the origin before anything is painted', () => {
        expect(viewport.getViewportX()).toBe(0);
        expect(viewport.getViewportY()).toBe(0);
    });

    it('puts the middle of the graph on the middle of the canvas', () => {
        paintTree();
        const centre = screenCentre();

        // The bounds used for centring ignore node size, so half a node is the tolerance.
        expect(centre.x).toBeCloseTo(WIDTH / 2, -2);
        expect(centre.y).toBeCloseTo(HEIGHT / 2, -2);
        expect(Math.abs(centre.x - WIDTH / 2)).toBeLessThan(LAYOUT_CONFIG.nodeWidth);
        expect(Math.abs(centre.y - HEIGHT / 2)).toBeLessThan(LAYOUT_CONFIG.nodeHeight);
    });

    it('moves the viewport away from the origin, rather than leaving the graph top-left', () => {
        paintTree();

        expect(viewport.getViewportX()).not.toBe(0);
        expect(viewport.getViewportY()).not.toBe(0);
    });

    it('re-centres when a new graph is painted, as a filter or a root change does', () => {
        paintTree();
        const first = { x: viewport.getViewportX(), y: viewport.getViewportY() };

        store.paint(graphResponse({
            root_node: ciNode(9, 0),
            child_nodes: Array.from({ length: 6 }, (_, i) => ciNode(i + 10, 0)),
            child_edges: Array.from({ length: 6 }, (_, i) => ciEdge(9, i + 10))
        }));

        const centre = screenCentre();
        expect(centre.x).toBeCloseTo(WIDTH / 2, -2);
        expect(centre.y).toBeCloseTo(HEIGHT / 2, -2);
        expect({ x: viewport.getViewportX(), y: viewport.getViewportY() }).not.toEqual(first);
    });

    it('stays put when the graph only changes shape, so expanding does not jump the canvas', () => {
        paintTree();
        const after = { x: viewport.getViewportX(), y: viewport.getViewportY() };

        store.relayout();

        expect(viewport.getViewportX()).toBe(after.x);
        expect(viewport.getViewportY()).toBe(after.y);
    });
});
