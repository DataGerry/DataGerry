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
import { ChangeDetectionStrategy, Component, computed, ElementRef, inject, input, output } from '@angular/core';

import { getTextColorBasedOnBackground } from 'src/app/core/utils/color-utils';

import { EDGE_STYLES, EdgeStyle, LAYOUT_CONFIG } from '../../constants/graph.constants';
import { Connection, GraphNode } from '../../interfaces/graph.interfaces';
import { GraphDataService } from '../../services/graph-data.service';
import { GraphEditorStore, NodeTypeConfig } from '../../services/graph-editor.store';
import { GraphViewportService } from '../../services/graph-viewport.service';
import {
    calculateLabelPosition,
    calculatePath,
    getConnectionStrokeWidth
} from '../../utils/graph-path.util';

/** Distance back from the target node at which the arrow head sits. */
const ARROW_OFFSET = 60;

/** Heads declared in the <defs> of this component's template. */
const ARROW_MARKERS = {
    valid: 'url(#arrow-valid)',
    invalid: 'url(#arrow-invalid)',
    dataFlow: 'url(#arrow-data-flow)'
} as const;

/** Kept as the stylesheet drew it, since a broken edge is about the state and not the source. */
const INVALID_EDGE_STROKE = 'rgba(239, 68, 68, 0.4)';
const INVALID_EDGE_DASH = '8 4';

export interface NodePointerEvent {
    event: MouseEvent;
    node: GraphNode;
}

export interface ConnectionPointerEvent {
    event: MouseEvent;
    connection: Connection;
}

/**
 * The transformed layer: edges as SVG, nodes as cards. It reads the graph straight from the
 * store and reports gestures upward, so the shell keeps every pointer and menu decision.
 */
@Component({
    selector: 'cmdb-graph-canvas',
    templateUrl: './graph-canvas.component.html',
    changeDetection: ChangeDetectionStrategy.OnPush,
    host: {
        'class': 'graph-canvas',
        '[class.smooth-transition]': 'smooth()',
        '[style.transform]': 'transform()'
    },
    standalone: false
})
export class GraphCanvasComponent {
    readonly store = inject(GraphEditorStore);
    readonly element = inject<ElementRef<HTMLElement>>(ElementRef);

    private readonly graphData = inject(GraphDataService);
    private readonly graphViewport = inject(GraphViewportService);

    readonly viewportX = input(0);
    readonly viewportY = input(0);
    readonly zoom = input(1);
    readonly smooth = input(true);

    /** The clipping viewport, handed over after view init so off-screen nodes can be culled. */
    readonly container = input<ElementRef | null>(null);

    /** Layout eases x/y on the node objects themselves, so only this signals a move. */
    readonly frame = input(0);

    readonly nodePressed = output<NodePointerEvent>();
    readonly nodeClicked = output<NodePointerEvent>();
    readonly nodeExpandRequested = output<NodePointerEvent>();
    readonly nodeMenuRequested = output<NodePointerEvent>();
    readonly nodeFocusRequested = output<GraphNode>();
    readonly connectionClicked = output<ConnectionPointerEvent>();

    protected readonly transform = computed(
        () => `translate(${this.viewportX()}px, ${this.viewportY()}px) scale(${this.zoom()})`
    );

    /* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    calculatePath(conn: Connection): string {
        return calculatePath(conn, this.graphData.getNodeInstanceMap());
    }

    calculateLabelPosition(conn: Connection): { x: number; y: number } {
        return calculateLabelPosition(conn, this.store.nodes);
    }

    getConnectionStrokeWidth(conn: Connection): number {
        return this.edgeStyle(conn).width ?? getConnectionStrokeWidth(conn);
    }

    getConnectionStroke(conn: Connection): string {
        return conn.isValid ? this.edgeStyle(conn).stroke : INVALID_EDGE_STROKE;
    }

    getConnectionDash(conn: Connection): string | null {
        return conn.isValid ? this.edgeStyle(conn).dash : INVALID_EDGE_DASH;
    }

    /** An undirected edge gets no head, so neither end reads as the target. */
    getArrowMarker(conn: Connection): string | null {
        if (conn.undirected || conn.kind === 'cable') {
            return null;
        }

        if (!conn.isValid) {
            return ARROW_MARKERS.invalid;
        }

        return conn.dataFlow ? ARROW_MARKERS.dataFlow : ARROW_MARKERS.valid;
    }

    /** Places the invisible click target a fixed distance back from the target node. */
    getArrowPosition(conn: Connection): { x: number; y: number } {
        const fromNode = this.store.nodeByUid(conn.fromUid!);
        const toNode = this.store.nodeByUid(conn.toUid!);

        if (!fromNode || !toNode) {
            return { x: 0, y: 0 };
        }

        const { nodeWidth, nodeHeight } = LAYOUT_CONFIG;
        const fromCenterX = fromNode.x + nodeWidth / 2;
        const fromCenterY = fromNode.y + nodeHeight / 2;
        const toCenterX = toNode.x + nodeWidth / 2;
        const toCenterY = toNode.y + nodeHeight / 2;

        const dx = toCenterX - fromCenterX;
        const dy = toCenterY - fromCenterY;
        const distance = Math.sqrt(dx * dx + dy * dy);

        if (distance === 0) {
            return { x: toCenterX, y: toCenterY };
        }

        return {
            x: toCenterX - (dx / distance) * ARROW_OFFSET,
            y: toCenterY - (dy / distance) * ARROW_OFFSET
        };
    }

    shouldShowNode(node: GraphNode): boolean {
        return this.graphViewport.shouldShowNode(node, this.store.nodes.length, this.container() ?? undefined);
    }

    typeConfig(type: string): NodeTypeConfig | undefined {
        return this.store.typeConfig(type);
    }

    textColor(node: GraphNode): string {
        return getTextColorBasedOnBackground(node?.color);
    }

    isNodeHighlighted(node: GraphNode): boolean {
        const hovered = this.store.hoveredConnection;
        return !!hovered && (hovered.from === node?.id || hovered.to === node?.id);
    }

    isConnectionHighlighted(conn: Connection): boolean {
        const { hoveredNode, selectedNode } = this.store;
        return (!!hoveredNode && (conn?.from === hoveredNode.id || conn?.to === hoveredNode.id))
            || (!!selectedNode && (conn?.from === selectedNode.id || conn?.to === selectedNode.id));
    }

    /** Parallel edges share a node pair, so the relation label is part of the key. */
    connectionKey(conn: Connection): string {
        return `${conn.fromUid}-${conn.toUid}-${conn.relationLabel}`;
    }

    /* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    private edgeStyle(conn: Connection): EdgeStyle {
        return EDGE_STYLES[conn.kind ?? 'unknown'] ?? EDGE_STYLES.unknown;
    }
}
