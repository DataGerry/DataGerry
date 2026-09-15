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
import { LAYOUT_CONFIG } from '../constants/graph.constants';
import { Connection, GraphNode, NodeGroup } from '../interfaces/graph.interfaces';
import { connection, graphNode, instanceMap } from '../testing/graph-fixtures';
import { GraphLayoutService } from './graph-layout.service';

/**
 * Characterization of the hierarchical layout. These coordinates are the contract the
 * top-down strategy has to reproduce once the layout moves behind an interface.
 *
 * Every node starts at (0,0), so the first pass writes positions synchronously - the
 * animation path only engages once a node already has a non-zero position.
 */
describe('GraphLayoutService (characterization)', () => {
    const { centerX, centerY, horizontalSpacing, verticalSpacing, nodeWidth, nodeHeight } = LAYOUT_CONFIG;
    let service: GraphLayoutService;

    beforeEach(() => {
        service = new GraphLayoutService();
    });

    /** The component always rebinds the anchor closures before laying out. */
    function layout(nodes: GraphNode[], connections: Connection[]): NodeGroup[] {
        const groups: NodeGroup[] = [];
        service.updateAnchorCalculations(connections, instanceMap(nodes));
        service.performHierarchicalLayout(nodes, groups);
        return groups;
    }

    describe('root level', () => {
        it('centres a single root horizontally and snaps it to the grid vertically', () => {
            const root = graphNode({ id: 1, level: 0 });

            layout([root], []);

            // centerY (450) is not a multiple of the 20px grid, and the 30px snap
            // threshold is wider than the grid, so the root always lands on 460.
            expect(root.x).toBe(centerX);
            expect(root.y).toBe(460);
        });

        it('spreads multiple roots around the centre', () => {
            const a = graphNode({ id: 1, level: 0, uid: 'a' });
            const b = graphNode({ id: 2, level: 0, uid: 'b' });

            layout([a, b], []);

            expect(a.x).toBe(centerX - horizontalSpacing / 2);
            expect(b.x).toBe(centerX + horizontalSpacing / 2);
        });
    });

    describe('child levels', () => {
        it('places a level below the root at a fixed vertical offset', () => {
            const root = graphNode({ id: 1, level: 0, uid: 'root' });
            const child = graphNode({ id: 2, level: 1, uid: 'child', isRoot: false });
            const conn = connection({
                from: 1, to: 2, fromLevel: 0, toLevel: 1, fromUid: 'root', toUid: 'child'
            });

            layout([root, child], [conn]);

            expect(child.y).toBe(centerY + verticalSpacing);
        });

        it('centres a single child under its parent', () => {
            const root = graphNode({ id: 1, level: 0, uid: 'root' });
            const child = graphNode({ id: 2, level: 1, uid: 'child', isRoot: false });
            const conn = connection({
                from: 1, to: 2, fromLevel: 0, toLevel: 1, fromUid: 'root', toUid: 'child'
            });

            layout([root, child], [conn]);

            expect(child.x).toBe(centerX);
        });

        it('spreads siblings evenly around their shared parent', () => {
            const root = graphNode({ id: 1, level: 0, uid: 'root' });
            const first = graphNode({ id: 2, level: 1, uid: 'c1', isRoot: false });
            const second = graphNode({ id: 3, level: 1, uid: 'c2', isRoot: false });
            const conns = [
                connection({ from: 1, to: 2, fromLevel: 0, toLevel: 1, fromUid: 'root', toUid: 'c1' }),
                connection({ from: 1, to: 3, fromLevel: 0, toLevel: 1, fromUid: 'root', toUid: 'c2' })
            ];

            layout([root, first, second], conns);

            expect(first.x).toBe(centerX - horizontalSpacing / 2);
            expect(second.x).toBe(centerX + horizontalSpacing / 2);
        });
    });

    describe('parent levels', () => {
        it('places a level above the root at a negative vertical offset', () => {
            const root = graphNode({ id: 1, level: 0, uid: 'root' });
            const parent = graphNode({ id: 2, level: -1, uid: 'parent', isRoot: false });
            const conn = connection({
                from: 2, to: 1, fromLevel: -1, toLevel: 0, fromUid: 'parent', toUid: 'root'
            });

            layout([root, parent], [conn]);

            expect(parent.y).toBe(centerY - verticalSpacing);
            expect(parent.x).toBe(centerX);
        });
    });

    describe('node groups', () => {
        it('emits one band per level, offset by half a node box', () => {
            const root = graphNode({ id: 1, level: 0, uid: 'root' });
            const child = graphNode({ id: 2, level: 1, uid: 'child', isRoot: false });
            const conn = connection({
                from: 1, to: 2, fromLevel: 0, toLevel: 1, fromUid: 'root', toUid: 'child'
            });

            const groups = layout([root, child], [conn]);

            expect(groups.map(g => g.level)).toEqual([0, 1]);
            expect(groups[0].y).toBe(centerY - nodeHeight / 2);
            expect(groups[1].y).toBe(centerY + verticalSpacing - nodeHeight / 2);
            expect(groups[1].x).toBe(centerX - nodeWidth / 2);
        });

        it('replaces the previous bands rather than appending to them', () => {
            const root = graphNode({ id: 1, level: 0, uid: 'root' });
            const groups: NodeGroup[] = [];

            service.updateAnchorCalculations([], instanceMap([root]));
            service.performHierarchicalLayout([root], groups);
            service.performHierarchicalLayout([root], groups);

            expect(groups.length).toBe(1);
        });
    });

    describe('magnetic snap', () => {
        it('aligns a node onto a neighbour that sits within the snap threshold', () => {
            const a = graphNode({ id: 1, level: 0, uid: 'a', x: 0, y: 0 });
            const b = graphNode({ id: 2, level: 0, uid: 'b', x: 0, y: 0 });
            service.setMagneticSnap(true);

            layout([a, b], []);

            // Two roots are a full horizontalSpacing apart, well outside the threshold.
            expect(Math.abs(a.x - b.x)).toBe(horizontalSpacing);
        });

        it('leaves positions on exact multiples of the grid when snapping is off', () => {
            const root = graphNode({ id: 1, level: 0, uid: 'root' });
            service.setMagneticSnap(false);

            layout([root], []);

            expect(root.x).toBe(centerX);
            expect(root.y).toBe(centerY);
        });
    });
});
