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
import { connection, graphNode, instanceMap } from '../testing/graph-fixtures';
import {
    calculateLabelPosition,
    calculatePath,
    getConnectionStrokeWidth,
    validateConnections
} from './graph-path.util';

/**
 * Characterization of the edge geometry. These assertions describe the renderer as it
 * behaves today and must survive the refactor unchanged.
 */
describe('graph-path util (characterization)', () => {
    const { nodeWidth, nodeHeight } = LAYOUT_CONFIG;

    describe('calculatePath', () => {
        it('returns an empty path when either endpoint is missing from the instance map', () => {
            const from = graphNode({ id: 1, level: 0 });
            const conn = connection({ from: 1, to: 2, fromLevel: 0, toLevel: 1 });

            expect(calculatePath(conn, instanceMap([from]))).toBe('');
        });

        it('draws a straight line when the horizontal gap is under 50px', () => {
            const from = graphNode({ id: 1, level: 0, x: 100, y: 0 });
            const to = graphNode({ id: 2, level: 1, x: 130, y: 300 });
            const conn = connection({ from: 1, to: 2, fromLevel: 0, toLevel: 1 });

            const startX = 100 + nodeWidth / 2;
            const endX = 130 + nodeWidth / 2;

            expect(calculatePath(conn, instanceMap([from, to])))
                .toBe(`M ${startX} ${0 + nodeHeight} L ${endX} ${300}`);
        });

        it('draws a cubic bezier through the vertical midpoint when the gap is 50px or more', () => {
            const from = graphNode({ id: 1, level: 0, x: 0, y: 0 });
            const to = graphNode({ id: 2, level: 1, x: 400, y: 300 });
            const conn = connection({ from: 1, to: 2, fromLevel: 0, toLevel: 1 });

            const startX = 0 + nodeWidth / 2;
            const endX = 400 + nodeWidth / 2;
            const startY = 0 + nodeHeight;
            const endY = 300;
            const midY = (startY + endY) / 2;

            expect(calculatePath(conn, instanceMap([from, to])))
                .toBe(`M ${startX} ${startY} C ${startX} ${midY}, ${endX} ${midY}, ${endX} ${endY}`);
        });

        it('swaps the endpoints when the source sits on a parent level, so parent edges are drawn upward', () => {
            const parent = graphNode({ id: 1, level: -1, x: 0, y: 0, isRoot: false });
            const root = graphNode({ id: 2, level: 0, x: 400, y: 300 });
            const conn = connection({ from: 1, to: 2, fromLevel: -1, toLevel: 0 });

            // `reverse` makes the root the start node, so the path begins at the root's box.
            const startX = 400 + nodeWidth / 2;
            const endX = 0 + nodeWidth / 2;
            const startY = 300;
            const endY = 0 + nodeHeight;
            const midY = (startY + endY) / 2;

            expect(calculatePath(conn, instanceMap([parent, root])))
                .toBe(`M ${startX} ${startY} C ${startX} ${midY}, ${endX} ${midY}, ${endX} ${endY}`);
        });

        it('leaves from the top of the start node when the start sits below the end', () => {
            const from = graphNode({ id: 1, level: 0, x: 0, y: 500 });
            const to = graphNode({ id: 2, level: 1, x: 400, y: 0 });
            const conn = connection({ from: 1, to: 2, fromLevel: 0, toLevel: 1 });

            const path = calculatePath(conn, instanceMap([from, to]));

            // startY = start node top, endY = end node bottom
            expect(path.startsWith(`M ${0 + nodeWidth / 2} ${500} `)).toBeTrue();
            expect(path.endsWith(`${400 + nodeWidth / 2} ${0 + nodeHeight}`)).toBeTrue();
        });
    });

    describe('calculateLabelPosition', () => {
        it('returns the midpoint between the source bottom edge and the target top edge', () => {
            const from = graphNode({ id: 1, level: 0, x: 0, y: 0 });
            const to = graphNode({ id: 2, level: 1, x: 400, y: 300 });
            const conn = connection({ from: 1, to: 2, fromLevel: 0, toLevel: 1 });

            expect(calculateLabelPosition(conn, [from, to])).toEqual({
                x: ((0 + nodeWidth / 2) + (400 + nodeWidth / 2)) / 2,
                y: ((0 + nodeHeight) + 300) / 2
            });
        });

        it('falls back to the origin when an endpoint cannot be matched by id and level', () => {
            const from = graphNode({ id: 1, level: 0 });
            const conn = connection({ from: 1, to: 999, fromLevel: 0, toLevel: 1 });

            expect(calculateLabelPosition(conn, [from])).toEqual({ x: 0, y: 0 });
        });
    });

    describe('getConnectionStrokeWidth', () => {
        it('uses the base width when no strength is set', () => {
            expect(getConnectionStrokeWidth(connection({ strength: undefined }))).toBe(3);
        });

        it('scales with strength', () => {
            expect(getConnectionStrokeWidth(connection({ strength: 2 }))).toBe(6);
        });

        it('caps the multiplier at 3', () => {
            expect(getConnectionStrokeWidth(connection({ strength: 99 }))).toBe(9);
        });
    });

    describe('validateConnections', () => {
        it('drops connections whose endpoints are no longer rendered', () => {
            const from = graphNode({ id: 1, level: 0 });
            const conn = connection({ from: 1, to: 2, fromLevel: 0, toLevel: 1 });

            expect(validateConnections([conn], instanceMap([from]))).toEqual([]);
        });

        it('drops connections that do not span exactly one level', () => {
            const from = graphNode({ id: 1, level: 0 });
            const to = graphNode({ id: 2, level: 2 });
            const conn = connection({ from: 1, to: 2, fromLevel: 0, toLevel: 2 });

            expect(validateConnections([conn], instanceMap([from, to]))).toEqual([]);
        });

        it('keeps one connection per ordered uid pair and discards later duplicates', () => {
            const from = graphNode({ id: 1, level: 0 });
            const to = graphNode({ id: 2, level: 1 });
            const first = connection({ from: 1, to: 2, fromLevel: 0, toLevel: 1 });
            const duplicate = connection({ from: 1, to: 2, fromLevel: 0, toLevel: 1 });

            const kept = validateConnections([first, duplicate], instanceMap([from, to]));

            expect(kept.length).toBe(1);
            expect(kept[0]).toBe(first);
        });

        it('rewrites the levels on the surviving connection from the live nodes', () => {
            const from = graphNode({ id: 1, level: 0 });
            const to = graphNode({ id: 2, level: 1 });
            const conn = connection({
                from: 1,
                to: 2,
                fromLevel: 99,
                toLevel: 99,
                fromUid: from.uid,
                toUid: to.uid
            });

            const [kept] = validateConnections([conn], instanceMap([from, to]));

            expect(kept.fromLevel).toBe(0);
            expect(kept.toLevel).toBe(1);
            expect(kept.isValid).toBeTrue();
        });

        it('treats the reversed uid pair as a distinct connection', () => {
            const a = graphNode({ id: 1, level: 0 });
            const b = graphNode({ id: 2, level: 1 });
            const forward = connection({ from: 1, to: 2, fromLevel: 0, toLevel: 1 });
            const backward = connection({
                from: 2,
                to: 1,
                fromLevel: 1,
                toLevel: 0,
                fromUid: b.uid,
                toUid: a.uid
            });

            expect(validateConnections([forward, backward], instanceMap([a, b])).length).toBe(2);
        });
    });
});
