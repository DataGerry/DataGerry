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
import { GraphNode, NodeGroup } from '../interfaces/graph.interfaces';
import { LAYOUT_CONFIG } from '../constants/graph.constants';

@Injectable()
export class GraphLayoutService {
    private smoothTransitions = true;
    private enableMagneticSnap = true;
    private snapGrid = 20;

    setSmoothTransitions(enabled: boolean): void {
        this.smoothTransitions = enabled;
    }

    setMagneticSnap(enabled: boolean): void {
        this.enableMagneticSnap = enabled;
    }

    setSnapGrid(grid: number): void {
        this.snapGrid = grid;
    }

    performHierarchicalLayout(nodes: GraphNode[], nodeGroups: NodeGroup[]): void {
        const { horizontalSpacing, verticalSpacing, centerX, centerY } = LAYOUT_CONFIG;

        // Clear existing node groups
        nodeGroups.length = 0;

        // Bucket nodes by level
        const levels = new Map<number, GraphNode[]>();
        nodes?.forEach(n => {
            if (!levels?.has(n?.level)) levels.set(n?.level, []);
            levels?.get(n?.level)!?.push(n);
        });
        const orderedLevels = Array.from(levels?.keys())?.sort((a, b) => a - b);

        // Root (level 0) – keep centred
        if (levels.has(0)) {
            this.positionRoot(levels?.get(0)!, centerX, centerY, horizontalSpacing, nodeGroups);
        }

        // Children (positive levels) – new compact anchoring
        orderedLevels?.filter(l => l > 0)?.forEach(l =>
            this.positionChildLevelNodes(l, levels, horizontalSpacing, verticalSpacing, nodeGroups)
        );

        // Parents (negative levels) – already compact
        orderedLevels?.filter(l => l < 0)?.reverse()?.forEach(l =>
            this.positionParentLevelNodes(l, levels, horizontalSpacing, verticalSpacing, nodeGroups)
        );

        if (this.enableMagneticSnap) this.applyMagneticSnap(nodes);
    }

    private positionRoot(
        rootNodes: GraphNode[],
        centerX: number,
        centerY: number,
        spacing: number,
        nodeGroups: NodeGroup[]
    ): void {
        const y = centerY;
        const totalW = (rootNodes.length - 1) * spacing;
        const startX = centerX - totalW / 2;

        rootNodes?.forEach((n, i) => this.setNodePosition(n, startX + i * spacing, y));

        nodeGroups.push({
            level: 0,
            nodes: rootNodes,
            x: startX - LAYOUT_CONFIG?.nodeWidth / 2,
            y: y - LAYOUT_CONFIG?.nodeHeight / 2,
            collapsed: false
        });
    }

    private positionChildLevelNodes(
        level: number,
        levels: Map<number, GraphNode[]>,
        hSpace: number,
        vSpace: number,
        nodeGroups: NodeGroup[]
    ): void {
        const kids = levels?.get(level)!;
        if (!kids?.length) { return; }

        const withAnchor = kids.map(k => ({
            node: k,
            anchor: this.avgParentAnchor(k, level - 1)
        })).sort((a, b) => a?.anchor - b?.anchor);

        const anchorsMean = withAnchor?.reduce((s, a) => s + a?.anchor, 0) / withAnchor?.length;
        let baseX = anchorsMean - ((kids?.length - 1) * hSpace) / 2;

        withAnchor?.forEach(({ node }, idx) => {
            this.setNodePosition(node, baseX + idx * hSpace,
                LAYOUT_CONFIG?.centerY + level * vSpace);
        });

        nodeGroups.push({
            level,
            nodes: kids,
            x: Math.min(...kids?.map(n => n?.x)) - LAYOUT_CONFIG?.nodeWidth / 2,
            y: LAYOUT_CONFIG?.centerY + level * vSpace - LAYOUT_CONFIG?.nodeHeight / 2,
            collapsed: false
        });
    }

    private positionParentLevelNodes(
        level: number,
        levels: Map<number, GraphNode[]>,
        hSpace: number,
        vSpace: number,
        nodeGroups: NodeGroup[]
    ): void {
        const pars = levels?.get(level)!;
        if (!pars?.length) { return; }

        const withAnchor = pars?.map(p => ({
            node: p,
            anchor: this.avgChildAnchor(p, level + 1)
        }))?.sort((a, b) => a?.anchor - b?.anchor);

        const anchorsMean = withAnchor?.reduce((s, a) => s + a?.anchor, 0) / withAnchor.length;
        let baseX = anchorsMean - ((pars?.length - 1) * hSpace) / 2;

        withAnchor?.forEach(({ node }, idx) => {
            this.setNodePosition(node, baseX + idx * hSpace,
                LAYOUT_CONFIG?.centerY + level * vSpace);
        });

        nodeGroups.push({
            level,
            nodes: pars,
            x: Math.min(...pars?.map(n => n?.x)) - LAYOUT_CONFIG?.nodeWidth / 2,
            y: LAYOUT_CONFIG?.centerY + level * vSpace - LAYOUT_CONFIG?.nodeHeight / 2,
            collapsed: false
        });
    }

    private avgParentAnchor(node: GraphNode, parentLevel: number): number {
        // This would need access to connections - will be injected via parameters
        return node?.x; // Placeholder
    }

    private avgChildAnchor(node: GraphNode, inwardLevel: number): number {
        // This would need access to connections - will be injected via parameters
        return node?.x; // Placeholder
    }

    private setNodePosition(node: GraphNode, newX: number, newY: number): void {
        if (this.smoothTransitions && node?.x !== 0 && node?.y !== 0) {
            node.targetX = newX;
            node.targetY = newY;
            this.animateNodePosition(node);
        } else {
            node.x = newX;
            node.y = newY;
        }
    }

    private animateNodePosition(node: GraphNode): void {
        const duration = LAYOUT_CONFIG?.animationDuration;
        const startX = node?.x;
        const startY = node?.y;
        const targetX = node?.targetX!;
        const targetY = node?.targetY!;
        const startTime = performance?.now();

        const animate = (currentTime: number) => {
            const elapsed = currentTime - startTime;
            const progress = Math.min(elapsed / duration, 1);
            const easeProgress = progress < 0.5
                ? 4 * progress * progress * progress
                : 1 - Math.pow(-2 * progress + 2, 3) / 2;

            node.x = startX + (targetX - startX) * easeProgress;
            node.y = startY + (targetY - startY) * easeProgress;

            if (progress < 1) {
                requestAnimationFrame(animate);
            } else {
                delete node?.targetX;
                delete node?.targetY;
            }
        };
        requestAnimationFrame(animate);
    }

    private applyMagneticSnap(nodes: GraphNode[]): void {
        const { magneticSnapThreshold } = LAYOUT_CONFIG;
        const grid = this.snapGrid;

        nodes.forEach(node => {
            const snapX = Math.round(node?.x / grid) * grid;
            const snapY = Math.round(node?.y / grid) * grid;

            if (Math.abs(node?.x - snapX) < magneticSnapThreshold) {
                node.x = snapX;
            }
            if (Math.abs(node?.y - snapY) < magneticSnapThreshold) {
                node.y = snapY;
            }

            nodes.forEach(otherNode => {
                if (node.id === otherNode?.id) return;
                if (Math.abs(node.x - otherNode?.x) < magneticSnapThreshold) {
                    node.x = otherNode?.x;
                }
                if (Math.abs(node.y - otherNode?.y) < magneticSnapThreshold) {
                    node.y = otherNode?.y;
                }
            });
        });
    }

    // Helper methods that need to be updated with connection data
    updateAnchorCalculations(
        connections: any[],
        nodeInstanceMap: Map<string, GraphNode>
    ): void {
        // Update the anchor calculation methods with connection data
        this.avgParentAnchor = (node: GraphNode, parentLevel: number): number => {
            const near = connections
                ?.filter(c => c?.isValid &&
                    ((c.toUid === node?.uid && c?.fromLevel === parentLevel) ||
                        (c.fromUid === node?.uid && c?.toLevel === parentLevel)))
                ?.map(c => nodeInstanceMap?.get(
                    c?.toUid === node?.uid ? c?.fromUid! : c?.toUid!))
                ?.filter(Boolean) as GraphNode[];

            return near?.length
                ? near?.reduce((s, n) => s + n?.x, 0) / near?.length
                : node?.x;
        };

        this.avgChildAnchor = (node: GraphNode, inwardLevel: number): number => {
            const neigh = connections
                ?.filter(c => c?.isValid &&
                    ((c?.fromUid === node?.uid && c?.toLevel === inwardLevel) ||
                        (c?.toUid === node?.uid && c?.fromLevel === inwardLevel)))
                ?.map(c => nodeInstanceMap?.get(
                    c?.fromUid === node?.uid ? c?.toUid! : c?.fromUid!))
                ?.filter(n => !!n) as GraphNode[];

            return neigh?.length
                ? neigh?.reduce((s, n) => s + n?.x, 0) / neigh?.length
                : node?.x;
        };
    }
}