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
import { UidBasedConnection } from '../interfaces/graph.interfaces';
import { ciEdge, connection, graphNode, relationMeta } from '../testing/graph-fixtures';
import {
    normalizeRelationIcon,
    resolveDirection,
    rowsFromIndexedEdges,
    rowsFromRenderedConnection,
    rowsFromTrackedConnections,
    toNodeDetails
} from './connection-modal.util';

/**
 * These rows previously came from three near-identical builders in the component.
 * The assertions describe the output each of those produced.
 */
describe('connection-modal util', () => {
    /** The shape a cable arrives in: no relation id, a source instead. */
    function portConnectionMeta() {
        return relationMeta({
            relation_id: null,
            relation_name: 'Port connection',
            relation_label: 'connected',
            relation_icon: 'fas fa-ethernet',
            source: 'port_connection'
        });
    }

    const fromNode = graphNode({ id: 1, level: 0, uid: 'from', label: 'web-01' });
    const toNode = graphNode({ id: 2, level: 1, uid: 'to', isRoot: false, label: 'db-01' });

    describe('normalizeRelationIcon', () => {
        it('adds the family token to a bare fa- name', () => {
            expect(normalizeRelationIcon('fa-network-wired')).toBe('fas fa-network-wired');
        });

        it('leaves an icon that already names its family', () => {
            expect(normalizeRelationIcon('far fa-link')).toBe('far fa-link');
            expect(normalizeRelationIcon('fab fa-github')).toBe('fab fa-github');
        });

        it('leaves a non Font Awesome icon alone', () => {
            expect(normalizeRelationIcon('location_on')).toBe('location_on');
        });

        it('passes through an absent icon', () => {
            expect(normalizeRelationIcon(undefined)).toBeUndefined();
            expect(normalizeRelationIcon('')).toBe('');
        });
    });

    describe('toNodeDetails', () => {
        it('projects only the fields the modal renders', () => {
            expect(toNodeDetails(fromNode)).toEqual({
                id: 1, label: 'web-01', type: 'Server', color: '#336699', level: 0
            });
        });
    });

    describe('resolveDirection', () => {
        it('reads downward as outgoing and upward as incoming', () => {
            expect(resolveDirection(fromNode, toNode)).toBe('outgoing');
            expect(resolveDirection(toNode, fromNode)).toBe('incoming');
        });

        it('reads a cable as bidirectional, whichever way it was drawn', () => {
            expect(resolveDirection(fromNode, toNode, connection({ undirected: true }))).toBe('bidirectional');
            expect(resolveDirection(toNode, fromNode, connection({ kind: 'cable' }))).toBe('bidirectional');
        });
    });

    describe('rowsFromIndexedEdges', () => {
        it('carries the first relation entry through and leaves the uids blank', () => {
            const rows = rowsFromIndexedEdges(
                [ciEdge(1, 2, [relationMeta({ relation_label: 'Hosts' })])],
                fromNode,
                toNode
            );

            expect(rows.length).toBe(1);
            expect(rows[0].from).toBe(1);
            expect(rows[0].to).toBe(2);
            expect(rows[0].fromLevel).toBe(0);
            expect(rows[0].toLevel).toBe(1);
            expect(rows[0].fromUid).toBe('');
            expect(rows[0].metadata!.relation_label).toBe('Hosts');
        });

        it('falls back to a location relation for the bare edge a location link arrives as', () => {
            const rows = rowsFromIndexedEdges([ciEdge(1, 2, [])], fromNode, toNode);

            expect(rows[0].metadata).toEqual({
                relation_id: 0,
                relation_label: 'Location',
                relation_color: '#666',
                relation_icon: 'location_on',
                relation_name: 'web-01',
                source: 'location'
            });
        });

        it('keeps the name of an edge that has a source but no relation id', () => {
            const rows = rowsFromIndexedEdges([ciEdge(1, 2, [portConnectionMeta()])], fromNode, toNode);

            expect(rows[0].metadata!.relation_name).toBe('Port connection');
            expect(rows[0].metadata!.relation_label).toBe('connected');
        });

        it('normalizes the icon on an edge that names a source', () => {
            const rows = rowsFromIndexedEdges(
                [ciEdge(1, 2, [relationMeta({ relation_icon: 'fa-plug', source: 'ipam' })])],
                fromNode,
                toNode
            );

            expect(rows[0].metadata!.relation_icon).toBe('fas fa-plug');
            expect(rows[0].metadata!.source).toBe('ipam');
        });

        it('returns one row per stored edge', () => {
            const rows = rowsFromIndexedEdges([ciEdge(1, 2), ciEdge(1, 2)], fromNode, toNode);

            expect(rows.length).toBe(2);
        });
    });

    describe('rowsFromTrackedConnections', () => {
        function tracked(overrides: Partial<UidBasedConnection> = {}): UidBasedConnection {
            return {
                fromNodeId: 1,
                toNodeId: 2,
                fromUid: 'from',
                toUid: 'to',
                metadata: relationMeta(),
                source: 'initial',
                instanceId: 1,
                ...overrides
            };
        }

        it('keeps the per-instance uids', () => {
            const rows = rowsFromTrackedConnections([tracked()], fromNode, toNode);

            expect(rows[0].fromUid).toBe('from');
            expect(rows[0].toUid).toBe('to');
            expect(rows[0].from).toBe(1);
            expect(rows[0].to).toBe(2);
        });

        it('falls back to a location relation when the edge names nothing', () => {
            const rows = rowsFromTrackedConnections(
                [tracked({ metadata: { relation_id: 0 } })],
                fromNode,
                toNode
            );

            expect(rows[0].metadata!.relation_label).toBe('Location');
        });

        it('reports a tracked port connection as itself, not as a location link', () => {
            const rows = rowsFromTrackedConnections(
                [tracked({ metadata: portConnectionMeta() })],
                fromNode,
                toNode
            );

            expect(rows[0].metadata!.relation_name).toBe('Port connection');
            expect(rows[0].metadata!.relation_label).toBe('connected');
            expect(rows[0].metadata!.source).toBe('port_connection');
        });
    });

    describe('rowsFromRenderedConnection', () => {
        it('rebuilds a single row from the rendered edge', () => {
            const rows = rowsFromRenderedConnection(
                connection({ from: 1, to: 2, relationLabel: 'Runs on', relationColor: '#f00' }),
                fromNode,
                toNode
            );

            expect(rows.length).toBe(1);
            expect(rows[0].metadata!.relation_label).toBe('Runs on');
            expect(rows[0].metadata!.relation_name).toBe('Runs on');
            expect(rows[0].metadata!.relation_color).toBe('#f00');
        });

        it('prefers the relation the edge carries over the label it is drawn with', () => {
            const rows = rowsFromRenderedConnection(
                connection({ relationLabel: 'connected', metadata: portConnectionMeta() }),
                fromNode,
                toNode
            );

            expect(rows[0].metadata!.relation_name).toBe('Port connection');
            expect(rows[0].metadata!.source).toBe('port_connection');
        });

        it('treats a missing or Unknown label as a location link', () => {
            const unknown = rowsFromRenderedConnection(
                connection({ relationLabel: 'Unknown' }), fromNode, toNode
            );
            const absent = rowsFromRenderedConnection(
                connection({ relationLabel: undefined }), fromNode, toNode
            );

            expect(unknown[0].metadata!.relation_label).toBe('Location');
            expect(absent[0].metadata!.relation_label).toBe('Location');
            expect(absent[0].metadata!.relation_name).toBe('web-01');
        });
    });
});
