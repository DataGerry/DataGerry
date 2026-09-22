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
import {
    CIEdge,
    CINode,
    CiExplorerPathHop,
    GraphRespWithRoot,
    LinkedObject,
    RelationMeta,
    TypeInfo
} from 'src/app/framework/models/ci-explorer.model';
import { CableSource, ResolvedCable } from '../../ports-overview/models/port-connection.types';

import { Connection, GraphNode } from '../interfaces/graph.interfaces';

/**
 * Builders for graph-editor specs. Each takes a partial override so a test states
 * only the fields it actually cares about.
 */

export function linkedObject(overrides: Partial<LinkedObject> = {}): LinkedObject {
    return {
        public_id: 1,
        type_id: 10,
        version: '1.0.0',
        creation_time: { $date: '2026-01-01T00:00:00Z' },
        author_id: 1,
        last_edit_time: null,
        editor_id: null,
        active: true,
        fields: [],
        multi_data_sections: [],
        ...overrides
    };
}

export function typeInfo(overrides: Partial<TypeInfo> = {}): TypeInfo {
    return {
        type_id: 10,
        label: 'Server',
        icon: 'fas fa-server',
        fields: [],
        type_color: '#336699',
        ...overrides
    };
}

export function ciNode(
    publicId: number,
    level: number,
    overrides: Partial<CINode> = {}
): CINode {
    const typeId = overrides.type_info?.type_id ?? 10;

    return {
        level,
        direction: level === 0 ? 'root' : level < 0 ? 'parent' : 'child',
        color: '#336699',
        title: `CI ${publicId}`,
        linked_object: linkedObject({ public_id: publicId, type_id: typeId }),
        type_info: typeInfo({ type_id: typeId }),
        ...overrides
    };
}

export function relationMeta(overrides: Partial<RelationMeta> = {}): RelationMeta {
    return {
        relation_id: 100,
        relation_name: 'runs-on',
        relation_label: 'Runs on',
        relation_icon: 'fas fa-link',
        relation_color: '#ff0000',
        ...overrides
    };
}

export function ciEdge(from: number, to: number, metadata: RelationMeta[] = [relationMeta()]): CIEdge {
    return { from, to, metadata };
}

export function resolvedCable(overrides: Partial<ResolvedCable> = {}): ResolvedCable {
    return {
        source: CableSource.INLINE,
        cable_ci_id: null,
        name: 'Patch A-12',
        type: 'Cat6',
        type_id: 7,
        length: '3 m',
        color: '#1e88e5',
        description: null,
        ...overrides
    };
}

/** A panel's internal pairing carries no cable, which is why `cable` is nullable here. */
export function pathHop(overrides: Partial<CiExplorerPathHop> = {}): CiExplorerPathHop {
    return {
        public_id: 41,
        endpoints: [191, 205],
        connection_type: 'CABLE',
        cable: resolvedCable(),
        ...overrides
    };
}

/** A UI node. `uid` defaults to a readable, stable value so assertions can name it. */
export function graphNode(overrides: Partial<GraphNode> = {}): GraphNode {
    const id = overrides.id ?? 1;
    const level = overrides.level ?? 0;

    return {
        id,
        uid: `uid-${id}-L${level}`,
        label: `CI ${id}`,
        type: 'Server',
        level,
        x: 0,
        y: 0,
        color: '#336699',
        expanded: false,
        isLoading: false,
        isRoot: level === 0,
        hasChildren: false,
        hasParents: false,
        fields: [],
        connectionCount: { parents: 0, children: 0 },
        status: 'active',
        ...overrides
    };
}

export function connection(overrides: Partial<Connection> = {}): Connection {
    const from = overrides.from ?? 1;
    const to = overrides.to ?? 2;
    const fromLevel = overrides.fromLevel ?? 0;
    const toLevel = overrides.toLevel ?? 1;

    return {
        from,
        to,
        fromLevel,
        toLevel,
        fromUid: `uid-${from}-L${fromLevel}`,
        toUid: `uid-${to}-L${toLevel}`,
        relationLabel: 'Runs on',
        relationColor: '#ff0000',
        relationIcon: 'fas fa-link',
        isValid: true,
        strength: 1,
        dataFlow: false,
        ...overrides
    };
}

export function instanceMap(nodes: GraphNode[]): Map<string, GraphNode> {
    return new Map(nodes.map(n => [n.uid, n]));
}

export function graphResponse(overrides: Partial<GraphRespWithRoot> = {}): GraphRespWithRoot {
    return {
        root_node: ciNode(1, 0),
        parent_nodes: [],
        child_nodes: [],
        parent_edges: [],
        child_edges: [],
        ...overrides
    };
}
