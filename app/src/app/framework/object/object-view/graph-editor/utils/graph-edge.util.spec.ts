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
import { ciEdge, pathHop, relationMeta, resolvedCable } from '../testing/graph-fixtures';
import { cableColorOf, edgeByNeighbour, edgeKind, edgeMeta, isUndirectedEdge, undirectedNeighbours } from './graph-edge.util';

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

    describe('edgeKind', () => {
        it('reads a port connection as a cable', () => {
            expect(edgeKind(portConnection())).toBe('cable');
        });

        it('reads an IPAM edge by its source', () => {
            expect(edgeKind(relationMeta({ relation_id: null, source: 'ipam' }))).toBe('ipam');
        });

        it('reads a modelled relation by its id', () => {
            expect(edgeKind(relationMeta())).toBe('relation');
        });

        it('treats absent metadata as a location edge, which the backend sends bare', () => {
            expect(edgeKind(undefined)).toBe('location');
        });

        it('does not guess at a source it has no styling for', () => {
            expect(edgeKind(relationMeta({ relation_id: null, source: 'something_new' }))).toBe('unknown');
        });

        it('does not call an unbacked edge a relation', () => {
            expect(edgeKind(relationMeta({ relation_id: null }))).toBe('unknown');
        });
    });

    describe('cableColorOf', () => {
        it('takes the colour of the first cabled hop', () => {
            const meta = relationMeta({
                path: [
                    pathHop({ cable: resolvedCable({ color: 'blue' }) }),
                    pathHop({ cable: resolvedCable({ color: '#ff0000' }) })
                ]
            });

            expect(cableColorOf(meta)).toBe('blue');
        });

        it('skips a panel pairing, which carries no cable', () => {
            const meta = relationMeta({
                path: [
                    pathHop({ connection_type: 'INTERNAL', cable: null }),
                    pathHop({ cable: resolvedCable({ color: '#8e44ad' }) })
                ]
            });

            expect(cableColorOf(meta)).toBe('#8e44ad');
        });

        it('refuses a colour that is not safe to paint', () => {
            const meta = relationMeta({ path: [pathHop({ cable: resolvedCable({ color: 'url(#evil)' }) })] });

            expect(cableColorOf(meta)).toBeNull();
        });

        it('answers null when there is no path at all', () => {
            expect(cableColorOf(relationMeta())).toBeNull();
        });
    });

    describe('edgeByNeighbour', () => {
        it('finds the far endpoint whichever way the edge points', () => {
            const edges = [ciEdge(1, 2), ciEdge(3, 1, [portConnection()])];
            const byNeighbour = edgeByNeighbour(edges, 1);

            expect(byNeighbour.get(2)?.kind).toBe('relation');
            expect(byNeighbour.get(3)?.kind).toBe('cable');
        });

        it('lets the cable win when a pair is both related and cabled', () => {
            const edges = [ciEdge(1, 2, [portConnection()]), ciEdge(1, 2)];

            expect(edgeByNeighbour(edges, 1).get(2)?.kind).toBe('cable');
        });

        it('leaves a neighbour it has no edge for unclaimed', () => {
            expect(edgeByNeighbour([ciEdge(4, 5)], 1).size).toBe(0);
        });
    });
});
