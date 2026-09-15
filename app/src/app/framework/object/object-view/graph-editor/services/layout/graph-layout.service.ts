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
import { Injectable, OnDestroy } from '@angular/core';

import { LAYOUT_CONFIG } from '../../constants/graph.constants';
import { GraphNode, NodeGroup } from '../../interfaces/graph.interfaces';
import { GraphLayoutInput, GraphLayoutStrategy, Point } from '../../models/graph-layout.types';
import { HierarchicalTopDownStrategy } from './hierarchical-top-down.strategy';

interface Transition {
    node: GraphNode;
    fromX: number;
    fromY: number;
    toX: number;
    toY: number;
}

/**
 * Runs the active layout strategy and moves the nodes to the positions it returns.
 *
 * Every node eases on one shared frame loop, so a re-layout part way through an earlier
 * one cancels it instead of leaving two loops writing to the same coordinates.
 */
@Injectable()
export class GraphLayoutService implements OnDestroy {
    private strategy: GraphLayoutStrategy = new HierarchicalTopDownStrategy();
    private frameHandle?: number;
    private onFrame?: () => void;

    /* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    ngOnDestroy(): void {
        this.cancelAnimation();
    }

    /* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    /** Swapping this is all a new orientation needs; nothing that renders has to change. */
    setStrategy(strategy: GraphLayoutStrategy): void {
        this.strategy = strategy;
    }

    activeStrategyId(): string {
        return this.strategy.id;
    }

    /** Called on every animated frame so an OnPush view knows the positions moved. */
    setFrameCallback(onFrame: () => void): void {
        this.onFrame = onFrame;
    }

    /**
     * Lays the graph out and rewrites `nodeGroups` in place, which is what the band
     * backgrounds and the minimap read.
     */
    layout(input: GraphLayoutInput, nodeGroups: NodeGroup[]): void {
        const { placements, groups } = this.strategy.apply(input);

        nodeGroups.length = 0;
        nodeGroups.push(...groups);

        this.moveTo(input.nodes, placements);
    }

    cancelAnimation(): void {
        if (this.frameHandle !== undefined) {
            cancelAnimationFrame(this.frameHandle);
            this.frameHandle = undefined;
        }
    }

    /* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    /** A node still sitting at the origin has never been placed, so it jumps rather than slides. */
    private moveTo(nodes: GraphNode[], placements: ReadonlyMap<string, Point>): void {
        const transitions: Transition[] = [];

        nodes.forEach(node => {
            const target = placements.get(node.uid);
            if (!target) {
                return;
            }

            if (node.x !== 0 && node.y !== 0) {
                node.targetX = target.x;
                node.targetY = target.y;
                transitions.push({ node, fromX: node.x, fromY: node.y, toX: target.x, toY: target.y });
                return;
            }

            node.x = target.x;
            node.y = target.y;
        });

        this.cancelAnimation();

        if (!transitions.length) {
            this.onFrame?.();
            return;
        }

        this.animate(transitions);
    }

    private animate(transitions: Transition[]): void {
        const duration = LAYOUT_CONFIG.animationDuration;
        let startTime: number | undefined;

        const step = (now: number): void => {
            startTime ??= now;
            const progress = Math.min((now - startTime) / duration, 1);
            const eased = easeInOutCubic(progress);

            transitions.forEach(({ node, fromX, fromY, toX, toY }) => {
                node.x = fromX + (toX - fromX) * eased;
                node.y = fromY + (toY - fromY) * eased;
            });

            this.onFrame?.();

            if (progress < 1) {
                this.frameHandle = requestAnimationFrame(step);
                return;
            }

            transitions.forEach(({ node }) => {
                delete node.targetX;
                delete node.targetY;
            });
            this.frameHandle = undefined;
        };

        this.frameHandle = requestAnimationFrame(step);
    }
}

function easeInOutCubic(progress: number): number {
    return progress < 0.5
        ? 4 * progress * progress * progress
        : 1 - Math.pow(-2 * progress + 2, 3) / 2;
}
