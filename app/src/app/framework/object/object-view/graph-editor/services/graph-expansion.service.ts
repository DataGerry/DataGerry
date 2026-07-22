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
import {
    CIEdge,
    CINode,
    GraphRespChildren,
    GraphRespParents
} from 'src/app/framework/models/ci-explorer.model';
import { GraphNode, Connection } from '../interfaces/graph.interfaces';
import { GraphDataService } from './graph-data.service';
import { firstValueFrom } from 'rxjs';
import { ConnectionTrackerService } from './connection-tracker.service';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { CI_EXPLORER_ITEM_LIMIT } from 'src/app/framework/services/ci-explorer.service';


@Injectable()
export class GraphExpansionService {

    constructor(
        private graphData: GraphDataService,
        private connectionTracker: ConnectionTrackerService,
        private toastService: ToastService
    ) { }

    async expandNodeInstance(
        ui: GraphNode,
        cn: CINode,
        nodes: GraphNode[],
        connections: Connection[],
        typesFilter: number[],
        relationsFilter: number[],
        nodeTypeConfigs: Map<string, { icon: string; gradient: string }>,
        withLocations: boolean = true,
        withIpamRelations: boolean = true
    ): Promise<void> {
        ui.isLoading = true;
        ui.expanded = true;
        const nodeCountBefore = nodes.length;

        try {
            await this.fetchAndAttach(cn, ui, nodes, connections, typesFilter, relationsFilter, nodeTypeConfigs, withLocations, withIpamRelations);
            this.trackExpansionConnections(ui, nodeCountBefore, nodes);

        } finally {
            ui.isLoading = false;
        }
    }

    collapseNodeInstance(
        ui: GraphNode,
        nodes: GraphNode[],
        connections: Connection[]
    ): void {
        const victims = this.getDescendantInstancesFromSpecificNode(ui, nodes, connections);
        const uidsToRemove = victims?.map(n => n.uid);
        this.connectionTracker.removeConnectionsForCollapsedNodes(uidsToRemove);
        this.graphData?.removeNodeInstancesByUID(nodes, connections, uidsToRemove);
        ui.expanded = false;
    }

    private async fetchAndAttach(
        cn: CINode,
        ui: GraphNode,
        nodes: GraphNode[],
        connections: Connection[],
        typesFilter: number[],
        relationsFilter: number[],
        nodeTypeConfigs: Map<string, { icon: string; gradient: string }>,
        withLocations: boolean = true,
        withIpamRelations: boolean = true
    ): Promise<void> {
        const id = cn?.linked_object?.public_id;
        this.graphData?.setSkipBackendEdges(true);

        const wantType = (n: CINode) =>
            typesFilter?.length === 0 ||
            typesFilter?.includes(n?.type_info?.type_id);

        try {
            let limitHit = false;
            const allExpansionEdges: CIEdge[] = [];
            const newUIDs: string[] = [];

            // PARENTS (level -1, -2, …)
            if ((cn as any)?.direction === 'parent' || (cn as any)?.direction === 'root') {
                // const res: GraphRespParents = await this.graphData.expandParent(
                //   id,
                //   typesFilter,
                //   relationsFilter
                // ).toPromise();

                const res: GraphRespParents = await firstValueFrom(
                    this.graphData?.expandParent(id, typesFilter, relationsFilter, withLocations, withIpamRelations)
                );
                const rawParents = this.graphData?.getNodes(res, 'parent') ?? [];
                if (rawParents.length >= CI_EXPLORER_ITEM_LIMIT) {
                    limitHit = true;
                }
                const parents = rawParents?.filter(wantType);
                parents?.forEach(p => { p.level = ui?.level - 1; (p as any).direction = 'parent'; });

                const parentEdges = this.graphData.getEdges(res, 'parent');

                parentEdges.forEach(edge => {
                    allExpansionEdges.push(edge); // Just collect edges, don't index yet
                });

                const before = nodes?.length;
                this.graphData?.mergeNodes(nodes, parents, nodeTypeConfigs);
                const added = nodes?.slice(before);

                added?.forEach(p => {
                    connections.push({
                        from: id, to: id,
                        fromLevel: p?.level, toLevel: ui?.level,
                        fromUid: p?.uid, toUid: ui?.uid,
                        relationLabel: 'parent',
                        relationColor: cn?.relation_color,
                        isValid: true, strength: 1
                    });
                    newUIDs.push(p?.uid);
                });
            }

            // CHILDREN (level +1, +2, …)
            if ((cn as any).direction === 'child' || (cn as any).direction === 'root') {
                // const res: GraphRespChildren = await this.graphData.expandChild(
                //   id,
                //   typesFilter,
                //   relationsFilter
                // ).toPromise();

                const res: GraphRespChildren = await firstValueFrom(
                    this.graphData?.expandChild(id, typesFilter, relationsFilter, withLocations, withIpamRelations)
                );

                const rawKids = this.graphData?.getNodes(res, 'child') ?? [];
                if (rawKids.length >= CI_EXPLORER_ITEM_LIMIT) {
                    limitHit = true;
                }
                const kids = rawKids.filter(wantType);
                kids.forEach(k => { k.level = ui?.level + 1; (k as any).direction = 'child'; });

                const childEdges = this.graphData.getEdges(res, 'child');

                childEdges.forEach(edge => {
                    allExpansionEdges.push(edge); // Just collect edges, don't index yet
                });

                const before = nodes?.length;
                this.graphData?.mergeNodes(nodes, kids, nodeTypeConfigs);
                const added = nodes?.slice(before);

                added?.forEach(k => {
                    connections.push({
                        from: id, to: id,
                        fromLevel: ui?.level, toLevel: k?.level,
                        fromUid: ui?.uid, toUid: k?.uid,
                        relationLabel: 'child',
                        relationColor: cn?.relation_color,
                        isValid: true, strength: 1
                    });
                    newUIDs.push(k?.uid);
                });
            }

            (this as any).lastExpansionEdges = allExpansionEdges;
            if (limitHit) {
                this.toastService.info(
                    `Showing only the first ${CI_EXPLORER_ITEM_LIMIT} nodes for this level. We can't show all results.`
                );
            }

        } catch (err) {
            ui.expanded = false;
        } finally {
            this.graphData?.setSkipBackendEdges(false);
        }
    }

    private getDescendantInstancesFromSpecificNode(
        root: GraphNode,
        nodes: GraphNode[],
        connections: Connection[]
    ): GraphNode[] {
        const nodeInstanceMap = this.graphData?.getNodeInstanceMap();
        const followOutgoing = root?.level >= 0;
        const isFurtherAway = (lvl: number) =>
            followOutgoing ? lvl > root?.level : lvl < root?.level;

        const q: GraphNode[] = [];
        const out: GraphNode[] = [];
        const seen = new Set<string>();

        // Seed the queue with the first hop
        connections
            .filter(c => c?.isValid && (
                followOutgoing ? c?.fromUid === root?.uid : c?.toUid === root?.uid))
            .forEach(c => {
                const nextUid = followOutgoing ? c?.toUid! : c?.fromUid!;
                const n = nodeInstanceMap?.get(nextUid);
                if (n && isFurtherAway(n?.level)) { q?.push(n); }
            });

        // BFS along the proper direction
        while (q?.length) {
            const cur = q?.shift()!;
            if (seen?.has(cur?.uid)) { continue; }
            seen?.add(cur?.uid);
            out.push(cur);

            connections
                ?.filter(c => c?.isValid && (
                    followOutgoing ? c?.fromUid === cur?.uid : c?.toUid === cur?.uid))
                ?.forEach(c => {
                    const nextUid = followOutgoing ? c?.toUid! : c?.fromUid!;
                    const n = nodeInstanceMap?.get(nextUid);
                    if (n && isFurtherAway(n?.level) && !seen?.has(n?.uid)) {
                        q?.push(n);
                    }
                });
        }

        return out;
    }

    private trackExpansionConnections(
        expandedNode: GraphNode,
        nodeCountBefore: number,
        allNodes: GraphNode[]
    ): void {
        const expansionEdges: CIEdge[] = (this as any).lastExpansionEdges || [];

        if (expansionEdges.length === 0) {
            return;
        }

        const nodeInstanceMap = new Map<string, GraphNode>();
        allNodes.forEach(node => {
            nodeInstanceMap.set(node.uid, node);
        });

        expansionEdges.forEach(edge => {
            const meta = Array.isArray(edge.metadata) ? edge.metadata[0] : edge.metadata;
        });

        this.connectionTracker.addConnectionsFromExpansion(
            expansionEdges,
            nodeInstanceMap
        );

        delete (this as any).lastExpansionEdges;
    }

}
