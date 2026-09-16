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
import { ciEdge, relationMeta } from '../testing/graph-fixtures';
import { edgeMeta, isUndirectedEdge, undirectedNeighbours } from './graph-edge.util';

describe('graph-edge.util', () => {
    const portConnection = () => relationMeta({ source: 'port_connection', undirected: true });

    describe('edgeMeta', () => {
        it('takes the first relation of the list', () => {
            const edge = ciEdge(1, 2, [relationMeta({ relation_label: 'First' }), relationMeta({ relation_label: 'Second' })]);

            expect(edgeMeta(edge)?.relation_label).toBe('First');
        });

        it('survives an edge with no relations at all', () => {
            expect(edgeMeta(ciEdge(1, 2, []))).toBeUndefined();
        });
    });

    describe('isUndirectedEdge', () => {
        it('reports a port connection as undirected', () => {
            expect(isUndirectedEdge(ciEdge(1, 2, [portConnection()]))).toBeTrue();
        });

        it('reports a modelled relation as directed', () => {
            expect(isUndirectedEdge(ciEdge(1, 2))).toBeFalse();
        });
    });

    describe('undirectedNeighbours', () => {
        it('collects the far endpoint whichever way the edge points', () => {
            const edges = [
                ciEdge(1, 2, [portConnection()]),
                ciEdge(3, 1, [portConnection()])
            ];

            expect(undirectedNeighbours(edges, 1)).toEqual(new Set([2, 3]));
        });

        it('ignores directed edges and edges that miss the node', () => {
            const edges = [
                ciEdge(1, 2),
                ciEdge(4, 5, [portConnection()])
            ];

            expect(undirectedNeighbours(edges, 1).size).toBe(0);
        });
    });
});
