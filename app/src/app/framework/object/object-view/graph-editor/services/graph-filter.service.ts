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
import { Injectable } from '@angular/core';
import { GraphNode, Connection } from '../interfaces/graph.interfaces';

@Injectable()
export class GraphFilterService {
    private searchQuery = '';
    private nodeTypeFilter: string[] = [];
    private showOnlyConnected = false;
    private filterMode: 'OR' | 'AND' = 'OR';

    setSearchQuery(query: string): void {
        this.searchQuery = query;
    }

    setNodeTypeFilter(filter: string[]): void {
        this.nodeTypeFilter = [...filter];
    }

    setShowOnlyConnected(show: boolean): void {
        this.showOnlyConnected = show;
    }

    setFilterMode(mode: 'OR' | 'AND'): void {
        this.filterMode = mode;
    }

    getFilteredNodes(
        nodes: GraphNode[],
        connections: Connection[],
        selectedNode: GraphNode | null
    ): GraphNode[] {
        const root = nodes?.find(n => n?.isRoot);
        if (!root) { return []; }

        // Build the SET of selected type-ids
        const selectedTypeIds = new Set<number>();
        for (const tLabel of this.nodeTypeFilter) {
            const n = nodes?.find(n_ => n_?.type === tLabel && n_?.ciNode);
            if (n?.ciNode?.type_info?.type_id !== undefined) {
                selectedTypeIds?.add(n?.ciNode?.type_info?.type_id);
            }
        }

        const matchesSearch = (node: GraphNode): boolean => {
            if (!this.searchQuery) { return true; }
            const q = this.searchQuery?.toLowerCase();
            return (
                node?.label?.toLowerCase()?.includes(q) ||
                node?.type?.toLowerCase()?.includes(q) ||
                node?.id?.toString()?.includes(q) ||
                node?.fields?.some(
                    f => f?.name?.toLowerCase()?.includes(q) || f?.value?.toLowerCase()?.includes(q)
                )
            );
        };

        // Collect visible ids via BFS that honours the "concrete path" rule
        const visibleIds = new Set<number>([root.id]);
        if (selectedTypeIds?.size > 0) {
            interface QState { node: GraphNode; typesSeen: Set<number>; }
            const queue: QState[] = [{ node: root, typesSeen: new Set() }];
            const visited = new Set<number>([root?.id]);

            while (queue?.length) {
                const { node, typesSeen } = queue?.shift()!;

                const neighbours = connections
                    ?.filter(c => c?.isValid && (c?.from === node?.id || c?.to === node?.id))
                    ?.map(c => this.getNodeById(nodes, c?.from === node?.id ? c?.to : c?.from))
                    ?.filter(n => !!n);

                for (const nb of neighbours) {
                    const nbTypeId = nb?.ciNode?.type_info?.type_id;
                    if (nbTypeId === undefined) { continue; }

                    if (!selectedTypeIds?.has(nbTypeId)) { continue; }

                    if (!visited?.has(nb?.id)) {
                        visited?.add(nb?.id);
                        const nextTypesSeen = new Set(typesSeen);
                        nextTypesSeen?.add(nbTypeId);
                        queue.push({ node: nb, typesSeen: nextTypesSeen });
                    }
                    visibleIds.add(nb?.id);
                }
            }

            // AND-mode: remove nodes that haven't accumulated all selected type-ids
            if (this.filterMode === 'AND' && selectedTypeIds?.size > 1) {
                const stillOk = new Set<number>([root?.id]);
                const seenMap = new Map<number, Set<number>>([[root?.id, new Set()]]);
                const queue2: number[] = [root?.id];

                while (queue2?.length) {
                    const id = queue2?.shift()!;
                    const currentSeen = seenMap?.get(id)!;

                    const neighbours = connections
                        ?.filter(c => c?.isValid && (c?.from === id || c?.to === id))
                        ?.map(c => this.getNodeById(nodes, c?.from === id ? c?.to : c?.from))
                        ?.filter(n => visibleIds?.has(n?.id));

                    for (const nb of neighbours) {
                        const nbTypeId = nb?.ciNode?.type_info?.type_id!;
                        const nextSeen = new Set(currentSeen);
                        nextSeen.add(nbTypeId);

                        const old = seenMap?.get(nb?.id);
                        if (!old || old?.size < nextSeen?.size) {
                            seenMap.set(nb?.id, nextSeen);
                            queue2.push(nb?.id);
                        }

                        if (nextSeen?.size === selectedTypeIds?.size) {
                            stillOk.add(nb?.id);
                        }
                    }
                }

                visibleIds?.forEach(id => {
                    if (!stillOk?.has(id)) visibleIds?.delete(id);
                });
            }
        } else {
            nodes?.forEach(n => visibleIds.add(n?.id));
        }

        // Apply search and connection filters
        let result = nodes?.filter(n => visibleIds?.has(n?.id) && matchesSearch(n));

        if (this.showOnlyConnected && selectedNode) {
            const connected = new Set<number>([selectedNode?.id]);
            connections?.forEach(c => {
                if (c?.from === selectedNode!.id) connected.add(c?.to);
                if (c?.to === selectedNode!.id) connected.add(c?.from);
            });
            result = result?.filter(n => connected?.has(n?.id));
        }

        return result;
    }

    getVisibleConnections(nodes: GraphNode[], connections: Connection[]): Connection[] {
        const visibleIds = new Set(nodes?.map(n => n?.id));
        return connections?.filter(
            c => visibleIds?.has(c?.from) && visibleIds?.has(c?.to) && c?.isValid
        );
    }

    private getNodeById(nodes: GraphNode[], id: number): GraphNode | undefined {
        return nodes?.find(n => n?.id === id);
    }

    // Search functionality
    performSearch(nodes: GraphNode[]): GraphNode[] {
        if (!this.searchQuery) {
            return [];
        }
        const query = this.searchQuery?.toLowerCase();
        return nodes?.filter(n =>
            n?.label?.toLowerCase()?.includes(query) ||
            n?.type?.toLowerCase()?.includes(query) ||
            n?.fields?.some(f =>
                f?.name?.toLowerCase()?.includes(query) ||
                f?.value?.toLowerCase()?.includes(query)
            ) ||
            n?.id?.toString()?.includes(query)
        );
    }

    addToNodeTypeFilter(type: string): void {
        if (!this.nodeTypeFilter?.includes(type)) {
            this.nodeTypeFilter?.push(type);
        }
    }

    removeFromNodeTypeFilter(type: string): void {
        this.nodeTypeFilter = this.nodeTypeFilter?.filter(t => t !== type);
    }

    toggleNodeTypeFilter(type: string): void {
        if (this.nodeTypeFilter?.includes(type)) {
            this.removeFromNodeTypeFilter(type);
        } else {
            this.addToNodeTypeFilter(type);
        }
    }

    isNodeTypeFiltered(type: string): boolean {
        return this.nodeTypeFilter?.includes(type);
    }

    clearAllFilters(): void {
        this.searchQuery = '';
        this.nodeTypeFilter = [];
        this.showOnlyConnected = false;
    }

    getSearchQuery(): string {
        return this.searchQuery;
    }

    getNodeTypeFilter(): string[] {
        return [...this.nodeTypeFilter];
    }

    getShowOnlyConnected(): boolean {
        return this.showOnlyConnected;
    }

    getFilterMode(): 'OR' | 'AND' {
        return this.filterMode;
    }
}