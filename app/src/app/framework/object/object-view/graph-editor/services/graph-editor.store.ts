/*
* DATAGERRY - OpenSource Enterprise CMDB
* Copyright (C) 2026 becon GmbH
*
* This program is free software: you can redistribute it and/or modify
* it under the terms of the GNU Affero General Public License as
* published by the Free Software Foundation, either version 3 of the
* License, or (at your option) any later version.
*
* You should have received a copy of the GNU Affero General Public License
* along with this program. If not, see <https://www.gnu.org/licenses/>.
*/
import { computed, inject, Injectable, signal } from '@angular/core';
import { finalize } from 'rxjs/operators';

import { LoaderService } from 'src/app/core/services/loader.service';
import { CINode, GraphRespWithRoot } from 'src/app/framework/models/ci-explorer.model';
import { CI_EXPLORER_ITEM_LIMIT } from 'src/app/framework/services/ci-explorer.service';
import { ToastService } from 'src/app/layout/toast/toast.service';

import { Connection, FilterProfile, GraphNode, NodeGroup } from '../interfaces/graph.interfaces';
import { visibleConnections, visibleNodes } from '../utils/graph-filter.util';
import { buildAdjacencyIndex } from '../utils/graph-layout.util';
import { validateConnections } from '../utils/graph-path.util';
import { ConnectionTrackerService } from './connection-tracker.service';
import { GraphDataService } from './graph-data.service';
import { GraphExpansionService } from './graph-expansion.service';
import { GraphLayoutService } from './layout/graph-layout.service';

export type NodeTypeConfig = { icon: string; gradient: string };

/**
 * Owns the graph: what was loaded, what is selected, and every write that changes either.
 *
 * Nodes and connections stay plain mutable arrays because layout and expansion write to
 * the node objects in place. `topology` is bumped whenever that shape changes, and the
 * derived collections hang off it - so the filtering that used to run on every change
 * detection pass now runs once per actual change.
 *
 * Provided by the component, not in root, so two editors cannot share one graph.
 */
@Injectable()
export class GraphEditorStore {
    private readonly graphData = inject(GraphDataService);
    private readonly graphLayout = inject(GraphLayoutService);
    private readonly graphExpansion = inject(GraphExpansionService);
    private readonly connectionTracker = inject(ConnectionTrackerService);
    private readonly loaderService = inject(LoaderService);
    private readonly toastService = inject(ToastService);

    /* ------------------------------------------------------ STATE ----------------------------------------------------- */

    nodes: GraphNode[] = [];
    connections: Connection[] = [];
    nodeGroups: NodeGroup[] = [];

    readonly nodeTypeConfigs = new Map<string, NodeTypeConfig>();

    /** Bumped when the set of nodes or connections changes, not when they merely move. */
    private readonly topology = signal(0);

    readonly visibleNodes = computed(() => {
        this.topology();
        return visibleNodes(this.nodes);
    });

    readonly visibleConnections = computed(() => {
        this.topology();
        return visibleConnections(this.visibleNodes(), this.connections);
    });

    readonly nodeCount = computed(() => this.visibleNodes().length);

    /** The viewport lives in the shell, so centring a freshly painted graph is its job. */
    private onPainted: () => void = () => undefined;

    /** Bumped per animation frame while positions settle; OnPush views read it to pick up x/y. */
    private readonly positionVersion = signal(0);
    readonly frame = this.positionVersion.asReadonly();

    // Selection
    selectedNode: GraphNode | null = null;
    selectedConnection: Connection | null = null;
    selectedNodes = new Set<number>();

    // Hover
    hoveredNode: GraphNode | null = null;
    hoveredConnection: Connection | null = null;

    // Server-side filters
    rootNodeId: number | null = null;
    typesFilter: number[] = [];
    relationsFilter: number[] = [];
    withLocations = true;
    withIpamRelations = true;

    profiles: FilterProfile[] = [];

    readonly isLoading$ = this.loaderService.isLoading$;

    /* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    setPaintedCallback(onPainted: () => void): void {
        this.onPainted = onPainted;
    }

    /** Re-reads the graph. `reset` throws away everything first, for a filter or root change. */
    load(reset = false): void {
        if (reset) {
            this.nodes.length = 0;
            this.connections.length = 0;
            this.nodeGroups.length = 0;
            this.graphData.clearAllData();
            this.connectionTracker.clear();
            this.touchTopology();
        }

        this.loaderService.show();
        this.graphData.loadWithRoot(
            this.rootNodeId,
            this.typesFilter,
            this.relationsFilter,
            this.withLocations,
            this.withIpamRelations
        )
            .pipe(finalize(() => this.loaderService.hide()))
            .subscribe({
                next: response => this.paint(response),
                error: err => this.reportError(err?.error?.message)
            });
    }

    /**
     * Rebuilds the graph from a root response.
     *
     * A CI that is both a parent and a child of the root is rendered twice, once on each
     * side, so the two relationships stay visible as separate nodes.
     */
    paint(response: GraphRespWithRoot): void {
        this.nodes = [];
        this.connections = [];
        this.graphData.clearAllData();

        const root = response.root_node;
        root.level = 0;
        (root as CINode & { direction: string; isRoot: boolean }).direction = 'root';
        (root as CINode & { direction: string; isRoot: boolean }).isRoot = true;

        const parents = this.graphData.getNodes(response, 'parent');
        const children = this.graphData.getNodes(response, 'child');
        this.warnIfTruncated([parents.length, children.length]);

        const parentIds = new Set(parents.map(n => n.linked_object.public_id));
        const childIds = new Set(children.map(n => n.linked_object.public_id));
        const onBothSides = new Set([...parentIds].filter(id => childIds.has(id)));

        const placed = new Set<number>();
        const finalParents: CINode[] = [];
        const finalChildren: CINode[] = [];

        parents.forEach(node => {
            const id = node.linked_object.public_id;
            if (placed.has(id)) {
                return;
            }
            node.level = -1;
            (node as CINode & { direction: string }).direction = 'parent';
            finalParents.push(node);
            placed.add(id);
        });

        children.forEach(node => {
            const id = node.linked_object.public_id;

            if (onBothSides.has(id)) {
                const copy = { ...node, level: 1 } as CINode & { direction: string };
                copy.direction = 'child';
                finalChildren.push(copy);
                return;
            }

            if (placed.has(id)) {
                return;
            }
            node.level = 1;
            (node as CINode & { direction: string }).direction = 'child';
            finalChildren.push(node);
            placed.add(id);
        });

        this.graphData.mergeNodes(this.nodes, [root, ...finalParents, ...finalChildren], this.nodeTypeConfigs);

        const edges = [...this.graphData.getEdges(response, 'parent'), ...this.graphData.getEdges(response, 'child')];
        this.graphData.mergeEdges(this.connections, this.nodes, edges);
        this.connections = validateConnections(this.connections, this.graphData.getNodeInstanceMap());

        this.graphData.addExpandedNode(root.linked_object.public_id);
        this.relayout();

        edges.forEach(edge => this.graphData.storeAndIndexEdge(edge));
        this.connectionTracker.storeInitialConnections(edges, this.graphData.getNodeInstanceMap());
        this.onPainted();
    }

    /** Re-runs the layout and the per-node counts after any change to the graph shape. */
    relayout(): void {
        this.graphLayout.layout(
            {
                nodes: this.nodes,
                connections: this.connections,
                nodeInstanceMap: this.graphData.getNodeInstanceMap()
            },
            this.nodeGroups
        );
        this.updateNodeStates();
        this.touchTopology();
    }

    /**
     * Counts each node's neighbours by which side of it they sit on, which drives the
     * parent/child badges and the expand affordances.
     */
    updateNodeStates(): void {
        const instances = this.graphData.getNodeInstanceMap();
        const adjacency = buildAdjacencyIndex(this.connections);

        this.nodes.forEach(node => {
            let parents = 0;
            let children = 0;

            (adjacency.get(node.uid) ?? []).forEach(conn => {
                if (conn.fromUid === node.uid) {
                    const other = instances.get(conn.toUid!);
                    if (other) {
                        other.level < node.level ? parents++ : other.level > node.level ? children++ : undefined;
                    }
                }
                if (conn.toUid === node.uid) {
                    const other = instances.get(conn.fromUid!);
                    if (other) {
                        other.level < node.level ? parents++ : other.level > node.level ? children++ : undefined;
                    }
                }
            });

            node.connectionCount = { parents, children };
            node.hasParents = parents > 0;
            node.hasChildren = children > 0;
        });
    }

    /* ------------------------------------------------- EXPAND/COLLAPSE ------------------------------------------------ */

    async toggleExpand(node: GraphNode): Promise<void> {
        if (node.isLoading) {
            return;
        }

        if (node.isRoot) {
            this.toggleRoot(node);
            return;
        }

        node.expanded ? this.collapse(node) : await this.expand(node);
    }

    /** The root collapses the whole graph; with nothing else on screen it reloads instead. */
    private toggleRoot(root: GraphNode): void {
        if (this.nodes.some(node => !node.isRoot)) {
            const descendants = this.nodes.filter(node => !node.isRoot).map(node => node.uid);
            this.connectionTracker.removeConnectionsForCollapsedNodes(descendants);
            this.graphData.removeNodeInstancesByUID(this.nodes, this.connections, descendants);
            root.expanded = false;
            this.selectedConnection = null;
            this.relayout();
            return;
        }

        this.rootNodeId = root.id;
        this.load(true);
    }

    private async expand(node: GraphNode): Promise<void> {
        this.loaderService.show();
        try {
            await this.graphExpansion.expandNodeInstance(
                node,
                node.ciNode!,
                this.nodes,
                this.connections,
                this.typesFilter,
                this.relationsFilter,
                this.nodeTypeConfigs,
                this.withLocations,
                this.withIpamRelations
            );
            this.connections = validateConnections(this.connections, this.graphData.getNodeInstanceMap());
            this.relayout();
        } finally {
            this.loaderService.hide();
        }
    }

    private collapse(node: GraphNode): void {
        this.graphExpansion.collapseNodeInstance(node, this.nodes, this.connections);
        this.relayout();
    }

    expandIcon(node: GraphNode | null): string {
        return this.isOpen(node) ? 'unfold_less' : 'unfold_more';
    }

    expandLabel(node: GraphNode | null): string {
        return this.isOpen(node) ? 'Collapse' : 'Expand';
    }

    private isOpen(node: GraphNode | null): boolean {
        if (!node) {
            return false;
        }
        return node.isRoot ? this.nodes.some(n => !n.isRoot) : !!node.expanded;
    }

    /* ---------------------------------------------------- SELECTION --------------------------------------------------- */

    select(node: GraphNode, additive = false): void {
        if (!additive) {
            this.clearSelection();
        }
        this.selectedNode = node;
        this.selectedNodes.add(node.id);
    }

    toggleNodeSelection(node: GraphNode): void {
        if (this.selectedNodes.has(node.id)) {
            this.selectedNodes.delete(node.id);
            if (this.selectedNode?.id === node.id) {
                this.selectedNode = null;
            }
            return;
        }
        this.selectedNodes.add(node.id);
        this.selectedNode = node;
    }

    selectAll(): void {
        this.nodes.forEach(node => this.selectedNodes.add(node.id));
    }

    clearSelection(): void {
        this.selectedNodes.clear();
        this.selectedNode = null;
        this.selectedConnection = null;
    }

    selectConnection(conn: Connection): void {
        this.selectedConnection = conn;
        this.selectedNode = null;
        this.selectedNodes.clear();
    }

    /** Hides the selected nodes locally; nothing is deleted on the server. */
    removeSelected(): void {
        if (!this.selectedNodes.size) {
            return;
        }

        const doomed = new Set(this.selectedNodes);
        const uids = this.nodes.filter(node => doomed.has(node.id)).map(node => node.uid);

        this.connectionTracker.removeConnectionsForCollapsedNodes(uids);
        this.graphData.removeNodeInstancesByUID(this.nodes, this.connections, uids);
        this.clearSelection();
        this.relayout();
    }

    /* ----------------------------------------------------- LOOKUPS ---------------------------------------------------- */

    nodeByUid(uid: string): GraphNode | undefined {
        return this.graphData.getNodeInstanceMap().get(uid);
    }

    nodeById(id: number): GraphNode | undefined {
        return this.nodes.find(node => node.id === id);
    }

    nodeByIdAndLevel(id: number, level: number): GraphNode | undefined {
        return this.nodes.find(node => node.id === id && node.level === level);
    }

    typeConfig(type: string): NodeTypeConfig | undefined {
        return this.nodeTypeConfigs.get(type);
    }

    /** Node coordinates are mutated in place, so moving them has to be announced separately. */
    tick(): void {
        this.positionVersion.update(version => version + 1);
    }

    /** Reserved for large graphs; below the threshold the banner renders empty. */
    performanceHint(): string {
        const count = this.nodes.length;
        return count > 500 ? `Displaying ${count} nodes. Use filters for better performance.` : '';
    }

    /* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    private touchTopology(): void {
        this.topology.update(version => version + 1);
        this.tick();
    }

    private warnIfTruncated(counts: number[]): void {
        if (counts.some(count => count >= CI_EXPLORER_ITEM_LIMIT)) {
            this.toastService.info(
                `Showing only the first ${CI_EXPLORER_ITEM_LIMIT} nodes for this level. We can't show all results.`
            );
        }
    }

    /**
     * The single seam every failure passes through. It is deliberately silent, which is
     * what the component did before; wiring it to the toast is a behaviour change and is
     * being handled separately.
     */
    private reportError(message?: string): void {
        this.toastService.error(message || 'Something went wrong. Please try again.');
    }
}
