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
import { Connection, GraphNode } from '../interfaces/graph.interfaces';
import { LayoutAxes, Point } from '../models/graph-layout.types';
import { connection, graphNode, instanceMap } from '../testing/graph-fixtures';
import { buildAdjacencyIndex, computeHierarchicalLayout } from './graph-layout.util';

/**
 * The coordinates asserted here are the ones the previous GraphLayoutService produced.
 * They are the contract any layout strategy has to reproduce.
 */
describe('graph-layout util (characterization)', () => {
    const { centerX, centerY, horizontalSpacing, verticalSpacing, nodeWidth, nodeHeight } = LAYOUT_CONFIG;
    const TOP_DOWN: LayoutAxes = { levelAxis: 'y', siblingAxis: 'x' };

    function run(nodes: GraphNode[], connections: Connection[] = [], magneticSnap = true) {
        return computeHierarchicalLayout(
            { nodes, connections, nodeInstanceMap: instanceMap(nodes), magneticSnap },
            TOP_DOWN
        );
    }

    function at(placements: ReadonlyMap<string, Point>, uid: string): Point {
        return placements.get(uid)!;
    }

    describe('root level', () => {
        it('centres a single root horizontally and snaps it to the grid vertically', () => {
            const root = graphNode({ id: 1, level: 0, uid: 'root' });

            const { placements } = run([root]);

            // centerY (450) is not a multiple of the 20px grid, and the 30px snap
            // threshold is wider than the grid, so the root always lands on 460.
            expect(at(placements, 'root')).toEqual({ x: centerX, y: 460 });
        });

        it('spreads multiple roots around the centre', () => {
            const a = graphNode({ id: 1, level: 0, uid: 'a' });
            const b = graphNode({ id: 2, level: 0, uid: 'b' });

            const { placements } = run([a, b]);

            expect(at(placements, 'a').x).toBe(centerX - horizontalSpacing / 2);
            expect(at(placements, 'b').x).toBe(centerX + horizontalSpacing / 2);
        });
    });

    describe('child levels', () => {
        const root = () => graphNode({ id: 1, level: 0, uid: 'root' });

        it('places a level below the root at a fixed vertical offset', () => {
            const child = graphNode({ id: 2, level: 1, uid: 'child', isRoot: false });
            const conn = connection({ from: 1, to: 2, fromLevel: 0, toLevel: 1, fromUid: 'root', toUid: 'child' });

            const { placements } = run([root(), child], [conn]);

            expect(at(placements, 'child').y).toBe(centerY + verticalSpacing);
        });

        it('centres a single child under its parent', () => {
            const child = graphNode({ id: 2, level: 1, uid: 'child', isRoot: false });
            const conn = connection({ from: 1, to: 2, fromLevel: 0, toLevel: 1, fromUid: 'root', toUid: 'child' });

            const { placements } = run([root(), child], [conn]);

            expect(at(placements, 'child').x).toBe(centerX);
        });

        it('spreads siblings evenly around their shared parent', () => {
            const first = graphNode({ id: 2, level: 1, uid: 'c1', isRoot: false });
            const second = graphNode({ id: 3, level: 1, uid: 'c2', isRoot: false });
            const conns = [
                connection({ from: 1, to: 2, fromLevel: 0, toLevel: 1, fromUid: 'root', toUid: 'c1' }),
                connection({ from: 1, to: 3, fromLevel: 0, toLevel: 1, fromUid: 'root', toUid: 'c2' })
            ];

            const { placements } = run([root(), first, second], conns);

            expect(at(placements, 'c1').x).toBe(centerX - horizontalSpacing / 2);
            expect(at(placements, 'c2').x).toBe(centerX + horizontalSpacing / 2);
        });

        it('ignores invalid connections when anchoring', () => {
            const child = graphNode({ id: 2, level: 1, uid: 'child', isRoot: false, x: 0, y: 0 });
            const conn = connection({
                from: 1, to: 2, fromLevel: 0, toLevel: 1, fromUid: 'root', toUid: 'child', isValid: false
            });

            const { placements } = run([root(), child], [conn]);

            // With no usable anchor the band falls back to the node's own position.
            expect(at(placements, 'child').x).toBe(0);
        });
    });

    describe('parent levels', () => {
        it('places a level above the root at a negative vertical offset', () => {
            const root = graphNode({ id: 1, level: 0, uid: 'root' });
            const parent = graphNode({ id: 2, level: -1, uid: 'parent', isRoot: false });
            const conn = connection({
                from: 2, to: 1, fromLevel: -1, toLevel: 0, fromUid: 'parent', toUid: 'root'
            });

            const { placements } = run([root, parent], [conn]);

            expect(at(placements, 'parent')).toEqual({ x: centerX, y: centerY - verticalSpacing });
        });
    });

    describe('node groups', () => {
        it('emits one band per level, offset by half a node box', () => {
            const root = graphNode({ id: 1, level: 0, uid: 'root' });
            const child = graphNode({ id: 2, level: 1, uid: 'child', isRoot: false });
            const conn = connection({ from: 1, to: 2, fromLevel: 0, toLevel: 1, fromUid: 'root', toUid: 'child' });

            const { groups } = run([root, child], [conn]);

            expect(groups.map(g => g.level)).toEqual([0, 1]);
            expect(groups[0].y).toBe(centerY - nodeHeight / 2);
            expect(groups[1].y).toBe(centerY + verticalSpacing - nodeHeight / 2);
            expect(groups[1].x).toBe(centerX - nodeWidth / 2);
        });

        it('orders the bands root first, then children outward, then parents outward', () => {
            const nodes = [
                graphNode({ id: 1, level: 0, uid: 'root' }),
                graphNode({ id: 2, level: 1, uid: 'c1', isRoot: false }),
                graphNode({ id: 3, level: 2, uid: 'c2', isRoot: false }),
                graphNode({ id: 4, level: -1, uid: 'p1', isRoot: false }),
                graphNode({ id: 5, level: -2, uid: 'p2', isRoot: false })
            ];

            const { groups } = run(nodes);

            expect(groups.map(g => g.level)).toEqual([0, 1, 2, -1, -2]);
        });
    });

    describe('magnetic snap', () => {
        it('leaves positions exactly on the computed values when snapping is off', () => {
            const root = graphNode({ id: 1, level: 0, uid: 'root' });

            const { placements } = run([root], [], false);

            expect(at(placements, 'root')).toEqual({ x: centerX, y: centerY });
        });

        it('keeps two roots a full spacing apart, well outside the threshold', () => {
            const a = graphNode({ id: 1, level: 0, uid: 'a' });
            const b = graphNode({ id: 2, level: 0, uid: 'b' });

            const { placements } = run([a, b]);

            expect(Math.abs(at(placements, 'a').x - at(placements, 'b').x)).toBe(horizontalSpacing);
        });

        it('never snaps the two instances of one CI onto each other', () => {
            // Both instances share an id, which is what the snap pass compares.
            const root = graphNode({ id: 1, level: 0, uid: 'root' });
            const asParent = graphNode({ id: 5, level: -1, uid: 'p', isRoot: false });
            const asChild = graphNode({ id: 5, level: 1, uid: 'c', isRoot: false });

            const { placements } = run([root, asParent, asChild]);

            expect(at(placements, 'p').y).not.toBe(at(placements, 'c').y);
        });
    });

    describe('the layout leaves the nodes alone', () => {
        it('reports positions without writing them onto the nodes', () => {
            const root = graphNode({ id: 1, level: 0, uid: 'root', x: 0, y: 0 });

            run([root]);

            expect(root.x).toBe(0);
            expect(root.y).toBe(0);
        });
    });

    describe('buildAdjacencyIndex', () => {
        it('indexes each valid connection under both of its endpoints', () => {
            const conn = connection({ from: 1, to: 2, fromUid: 'a', toUid: 'b' });

            const index = buildAdjacencyIndex([conn]);

            expect(index.get('a')).toEqual([conn]);
            expect(index.get('b')).toEqual([conn]);
        });

        it('skips connections that are not valid', () => {
            const index = buildAdjacencyIndex([connection({ fromUid: 'a', toUid: 'b', isValid: false })]);

            expect(index.size).toBe(0);
        });

        it('collects every edge that touches the same node', () => {
            const first = connection({ from: 1, to: 2, fromUid: 'a', toUid: 'b' });
            const second = connection({ from: 1, to: 3, fromUid: 'a', toUid: 'c' });

            expect(buildAdjacencyIndex([first, second]).get('a')!.length).toBe(2);
        });
    });
});
