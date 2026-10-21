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
import { connection, graphNode } from '../testing/graph-fixtures';
import { visibleConnections, visibleNodes } from './graph-filter.util';

/**
 * Carries over the assertions from the `default settings` block of the old
 * GraphFilterService spec - the only configuration that was ever reachable.
 */
describe('graph-filter util', () => {
    describe('visibleNodes', () => {
        it('returns nothing when the graph has no root node', () => {
            expect(visibleNodes([graphNode({ id: 7, level: 1, isRoot: false })])).toEqual([]);
        });

        it('returns every node, in order, regardless of how they are connected', () => {
            const root = graphNode({ id: 1, level: 0 });
            const child = graphNode({ id: 2, level: 1, isRoot: false });
            const unconnected = graphNode({ id: 3, level: 1, uid: 'uid-3', isRoot: false });

            expect(visibleNodes([root, child, unconnected]).map(n => n.id)).toEqual([1, 2, 3]);
        });

        it('keeps duplicate instances of the same CI at different levels', () => {
            const root = graphNode({ id: 1, level: 0 });
            const asParent = graphNode({ id: 5, level: -1, uid: 'uid-5-L-1', isRoot: false });
            const asChild = graphNode({ id: 5, level: 1, uid: 'uid-5-L1', isRoot: false });

            expect(visibleNodes([root, asParent, asChild]).map(n => n.uid))
                .toEqual(['uid-1-L0', 'uid-5-L-1', 'uid-5-L1']);
        });

        it('hands back a new array so callers cannot mutate the graph through it', () => {
            const nodes = [graphNode({ id: 1, level: 0 })];

            expect(visibleNodes(nodes)).not.toBe(nodes);
        });

        it('copes with an empty graph', () => {
            expect(visibleNodes([])).toEqual([]);
        });
    });

    describe('visibleConnections', () => {
        it('keeps only valid connections whose endpoints are both visible', () => {
            const root = graphNode({ id: 1, level: 0 });
            const child = graphNode({ id: 2, level: 1, isRoot: false });
            const shown = connection({ from: 1, to: 2 });
            const dangling = connection({ from: 1, to: 99, toLevel: 1 });
            const invalid = connection({ from: 1, to: 2, isValid: false });

            expect(visibleConnections([root, child], [shown, dangling, invalid])).toEqual([shown]);
        });

        it('treats a connection with no validity flag as invalid', () => {
            const root = graphNode({ id: 1, level: 0 });
            const child = graphNode({ id: 2, level: 1, isRoot: false });

            expect(visibleConnections([root, child], [connection({ isValid: undefined })])).toEqual([]);
        });

        it('drops everything when no node is visible', () => {
            expect(visibleConnections([], [connection()])).toEqual([]);
        });
    });
});
