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
import { CIEdge, RelationMeta } from 'src/app/framework/models/ci-explorer.model';

import { ConnectionDetailsData, NodeDetailsData } from '../modals/connection-details/connection-details-modal.component';
import { Connection, GraphNode, UidBasedConnection } from '../interfaces/graph.interfaces';

/** Shown when an edge carries no relation, which is how location links arrive. */
const LOCATION_RELATION = {
    relation_id: 0,
    relation_label: 'Location',
    relation_color: '#666',
    relation_icon: 'location_on'
} as const;

/**
 * Font Awesome needs a family token. The backend sends bare `fa-name` strings for IPAM,
 * so the family is added back before the icon reaches the template.
 */
export function normalizeRelationIcon(icon?: string): string | undefined {
    if (!icon) {
        return icon;
    }

    const tokens = icon.trim().split(/\s+/);
    const hasFamily = tokens.some(t => ['fa', 'fas', 'far', 'fab', 'fal', 'fad'].includes(t));
    const hasFaName = tokens.some(t => t.startsWith('fa-'));

    return hasFaName && !hasFamily ? `fas ${icon}` : icon;
}

export function toNodeDetails(node: GraphNode): NodeDetailsData {
    return {
        id: node.id,
        label: node.label,
        type: node.type,
        color: node.color,
        level: node.level
    };
}

/** Children sit at a higher level than their parents, which is what names the direction. */
export function resolveDirection(fromNode: GraphNode, toNode: GraphNode): 'incoming' | 'outgoing' {
    return fromNode.level < toNode.level ? 'outgoing' : 'incoming';
}

function toModalMetadata(meta: RelationMeta | undefined, fromNode: GraphNode): ConnectionDetailsData['metadata'] {
    if (meta?.source) {
        return {
            relation_id: meta.relation_id,
            relation_name: meta.relation_name,
            relation_label: meta.relation_label,
            relation_color: meta.relation_color,
            relation_icon: normalizeRelationIcon(meta.relation_icon),
            source: meta.source
        } as ConnectionDetailsData['metadata'];
    }

    if (!meta || !meta.relation_id) {
        return { ...LOCATION_RELATION, relation_name: fromNode.label };
    }

    return {
        relation_id: meta.relation_id,
        relation_name: meta.relation_name,
        relation_label: meta.relation_label,
        relation_color: meta.relation_color,
        relation_icon: meta.relation_icon
    } as ConnectionDetailsData['metadata'];
}

function firstMeta(metadata: RelationMeta[] | RelationMeta | undefined): RelationMeta | undefined {
    return Array.isArray(metadata) ? metadata[0] : metadata;
}

/** Edges pulled from the edge index, which is the richest source available. */
export function rowsFromIndexedEdges(
    edges: CIEdge[],
    fromNode: GraphNode,
    toNode: GraphNode
): ConnectionDetailsData[] {
    return edges.map(edge => ({
        from: edge.from,
        to: edge.to,
        fromLevel: fromNode.level,
        toLevel: toNode.level,
        fromUid: '',
        toUid: '',
        metadata: toModalMetadata(firstMeta(edge.metadata), fromNode)
    }));
}

/** Edges recorded per rendered instance, used when the index has nothing for the pair. */
export function rowsFromTrackedConnections(
    tracked: UidBasedConnection[],
    fromNode: GraphNode,
    toNode: GraphNode
): ConnectionDetailsData[] {
    return tracked.map(conn => ({
        from: conn.fromNodeId,
        to: conn.toNodeId,
        fromLevel: fromNode.level,
        toLevel: toNode.level,
        fromUid: conn.fromUid,
        toUid: conn.toUid,
        metadata: toModalMetadata(conn.metadata as RelationMeta, fromNode)
    }));
}

/** Last resort: rebuild a single row from what the rendered edge itself carries. */
export function rowsFromRenderedConnection(
    conn: Connection,
    fromNode: GraphNode,
    toNode: GraphNode
): ConnectionDetailsData[] {
    const hasRelation = !!conn.relationLabel && conn.relationLabel !== 'Unknown';

    return [{
        from: conn.from,
        to: conn.to,
        fromLevel: fromNode.level,
        toLevel: toNode.level,
        fromUid: conn.fromUid ?? '',
        toUid: conn.toUid ?? '',
        metadata: hasRelation
            ? {
                relation_id: 0,
                relation_name: conn.relationLabel,
                relation_label: conn.relationLabel,
                relation_color: conn.relationColor,
                relation_icon: conn.relationIcon
            } as ConnectionDetailsData['metadata']
            : { ...LOCATION_RELATION, relation_name: fromNode.label }
    }];
}
