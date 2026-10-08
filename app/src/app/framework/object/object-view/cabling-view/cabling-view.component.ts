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
*
* You should have received a copy of the GNU Affero General Public License
* along with this program. If not, see <https://www.gnu.org/licenses/>.
*/
import { AsyncPipe, NgTemplateOutlet } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, inject, input, signal } from '@angular/core';
import { takeUntilDestroyed, toObservable } from '@angular/core/rxjs-interop';

import { CoreModule } from 'src/app/core/core.module';
import { LoaderService } from 'src/app/core/services/loader.service';
import { CablingCableTooltipComponent } from './components/cabling-cable-tooltip/cabling-cable-tooltip.component';
import { CablingNodeComponent } from './components/cabling-node/cabling-node.component';
import {
    CABLE_CASING_STROKE,
    CABLING_GEOMETRY,
    CABLING_PAN_STEP,
    DEFAULT_DISPLAY_OPTIONS
} from './constants/cabling.constants';
import { CablingGesturesDirective } from './directives/cabling-gestures.directive';
import { CablingSelection, CablingSpotlight, CablingTrace } from './models/cabling-spotlight.types';
import { CablingTooltipView } from './models/cabling-tooltip.types';
import { CablingDisplayOptions, CablingNodeLayout } from './models/cabling.types';
import { CablingCableHoverStore } from './services/cabling-cable-hover.store';
import { CablingCanvasStore } from './services/cabling-canvas.store';
import { CablingSpotlightStore } from './services/cabling-spotlight.store';
import { CablingViewStore } from './services/cabling-view.store';
import {
    cablingBounds,
    layoutCablingEdges,
    layoutCablingNodes,
    offsetCablingNodes
} from './utils/cabling-layout.util';
import { spotlightTrace } from './utils/cabling-spotlight.util';
import { cableTooltip } from './utils/cabling-tooltip.util';
/* ------------------------------------------------------------------------------------------------------------------ */

/** A click on one of these has its own meaning: a link, a button, a cable or a cabled port. */
const SELF_HANDLED_CLICK = 'a, button, .cabling-edge__hit, .cabling-port.is-cabled';

const NO_PORTS: ReadonlySet<number> = new Set();


/**
 * The cabling of one object as a graph: the object, the objects its cables reach, and the cables
 * between their ports. Following a port outwards adds the object at its far end.
 */
@Component({
    selector: 'cmdb-cabling-view',
    standalone: true,
    imports: [
        AsyncPipe,
        NgTemplateOutlet,
        CoreModule,
        CablingGesturesDirective,
        CablingNodeComponent,
        CablingCableTooltipComponent
    ],
    templateUrl: './cabling-view.component.html',
    styleUrls: ['./cabling-view.component.scss'],
    providers: [CablingViewStore, CablingCanvasStore, CablingSpotlightStore, CablingCableHoverStore],
    changeDetection: ChangeDetectionStrategy.OnPush
})
export class CablingViewComponent {

    public readonly objectId = input<number | null>(null);

    protected readonly store = inject(CablingViewStore);
    protected readonly canvas = inject(CablingCanvasStore);
    protected readonly spotlightStore = inject(CablingSpotlightStore);
    private readonly cableHover = inject(CablingCableHoverStore);
    private readonly loaderService = inject(LoaderService);

    public readonly isLoading$ = this.loaderService.isLoading$;

    public readonly hoveredConnectionId = signal<number | null>(null);

    private readonly selection = signal<CablingSelection | null>(null);
    private readonly expandedNodeIds = signal<ReadonlySet<number>>(new Set());

    public readonly showFreePorts = signal(false);

    public readonly options = computed<CablingDisplayOptions>(() => ({
        ...DEFAULT_DISPLAY_OPTIONS,
        onlyConnected: !this.showFreePorts()
    }));

    /** Laid out apart from the drag offsets, so moving one card does not re-run the placement. */
    private readonly placedNodes = computed(() =>
        layoutCablingNodes(this.store.graph(), this.options(), this.expandedNodeIds()));

    public readonly nodes = computed(() => offsetCablingNodes(this.placedNodes(), this.canvas.offsets()));
    public readonly nodeList = computed(() => [...this.nodes().values()]);
    public readonly edges = computed(() => layoutCablingEdges(this.nodes(), this.store.graph().edges.values()));
    public readonly bounds = computed(() => cablingBounds(this.nodeList()));
    public readonly selectedConnectionId = computed(() => this.selection()?.connectionId ?? null);
    public readonly highlightedConnectionId = computed(() => this.selectedConnectionId() ?? this.hoveredConnectionId());

    public readonly isEmpty = computed(() => this.store.loaded() && !this.edges().length);

    private readonly trace = computed<CablingTrace | null>(() => {
        const selection = this.selection();

        return selection && this.spotlightStore.active() ? spotlightTrace(this.store.graph(), selection) : null;
    });

    /** Drawn a second time above the cards, so a cable running behind one can be followed. */
    public readonly raisedEdges = computed(() => {
        const raisedIds = this.trace()?.connectionIds ?? new Set([this.selectedConnectionId()]);

        return this.edges().filter((edge) => raisedIds.has(edge.connectionId));
    });

    /** Every card goes under the shade; only the ports on the picked trace rise above it. */
    public readonly spotlight = computed<CablingSpotlight | null>(() => (this.spotlightStore.active()
        ? { portIds: this.trace()?.portIds ?? NO_PORTS }
        : null));

    private readonly hoveredCableId = computed(() => this.cableHover.hover()?.connectionId ?? null);

    /** Keyed on the cable alone, so following the pointer does not rebuild its details. */
    private readonly hoveredCable = computed(() => {
        const connectionId = this.hoveredCableId();
        const edge = connectionId == null ? undefined : this.store.graph().edges.get(connectionId);

        return edge ? cableTooltip(edge, this.nodes()) : null;
    });

    /** Gone once the canvas moves under the pointer; the next pointer move places it again. */
    public readonly tooltip = computed<CablingTooltipView | null>(() => {
        const hover = this.cableHover.hover();
        const content = this.hoveredCable();

        return hover && content && !this.canvas.isPanning() && hover.viewport === this.canvas.viewport()
            ? { content, placement: hover.placement }
            : null;
    });

    public readonly casingStroke = CABLE_CASING_STROKE;
    public readonly endDotRadius = CABLING_GEOMETRY.endDotRadius;

    private readonly keyActions: Readonly<Record<string, () => void>> = {
        '+': () => this.canvas.zoomIn(),
        '=': () => this.canvas.zoomIn(),
        '-': () => this.canvas.zoomOut(),
        '_': () => this.canvas.zoomOut(),
        '0': () => this.fitToScreen(),
        'Escape': () => this.selection.set(null),
        's': () => this.toggleSpotlight(),
        'S': () => this.toggleSpotlight(),
        'ArrowLeft': () => this.canvas.panBy(CABLING_PAN_STEP, 0),
        'ArrowRight': () => this.canvas.panBy(-CABLING_PAN_STEP, 0),
        'ArrowUp': () => this.canvas.panBy(0, CABLING_PAN_STEP),
        'ArrowDown': () => this.canvas.panBy(0, -CABLING_PAN_STEP)
    };

/* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    constructor() {
        toObservable(this.objectId)
            .pipe(takeUntilDestroyed())
            .subscribe((objectId) => {
                this.resetView();
                this.store.load(objectId);
            });

        this.store.loaded$
            .pipe(takeUntilDestroyed())
            .subscribe(() => this.canvas.fit(this.bounds(), false));

        this.store.revealed$
            .pipe(takeUntilDestroyed())
            .subscribe((objectIds) => this.bringIntoView(objectIds));
    }

/* ---------------------------------------------------- EVENTS ------------------------------------------------------ */

    /** A touch only highlights; a pointer also gets the tooltip. */
    public onCableHover(event: PointerEvent, connectionId: number): void {
        this.hoveredConnectionId.set(connectionId);
        this.cableHover.track(event, connectionId);
    }


    public onCableLeave(): void {
        this.hoveredConnectionId.set(null);
        this.cableHover.clear();
    }


    /** The same port, or the cable itself, a second time puts the cable back behind the cards. */
    public onSelectConnection(selection: CablingSelection): void {
        if (this.canvas.dragged) {
            return;
        }

        const current = this.selection();
        const again = current?.connectionId === selection.connectionId
            && (selection.portId == null || selection.portId === current.portId);

        this.selection.set(again ? null : selection);
    }


    /** The cable line itself was clicked, so no card or port is picked. */
    public onSelectCable(connectionId: number): void {
        this.onSelectConnection({ connectionId, objectId: null, portId: null });
    }


    /** Any other click puts back the selected cable; only the toolbar turns the spotlight off. */
    public onCanvasClick(event: MouseEvent): void {
        const dragged = this.canvas.dragged;
        this.canvas.dragged = false;

        if (!dragged && !(event.target as Element | null)?.closest(SELF_HANDLED_CLICK)) {
            this.selection.set(null);
        }
    }


    /** Keys on the canvas itself; inside a card they belong to its buttons and links. */
    public onKeydown(event: KeyboardEvent): void {
        const action = this.keyActions[event.key];

        if (!action || event.target !== event.currentTarget || event.ctrlKey || event.metaKey || event.altKey) {
            return;
        }

        event.preventDefault();
        action();
    }

/* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    public toggleFreePorts(): void {
        this.showFreePorts.update((shown) => !shown);
    }


    public fitToScreen(): void {
        this.canvas.fit(this.bounds());
    }


    /** While on, everything goes under the shade but the picked port and its trace back to this object. */
    public toggleSpotlight(): void {
        this.spotlightStore.toggle();
    }


    /** Drops every expansion, move and unfolded card, and reads the object's ring again. */
    public resetGraph(): void {
        this.resetView();
        this.store.reload();
    }


    public toggleRows(objectId: number): void {
        this.expandedNodeIds.update((ids) => {
            const next = new Set(ids);

            if (!next.delete(objectId)) {
                next.add(objectId);
            }

            return next;
        });
    }

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    private resetView(): void {
        this.spotlightStore.turnOff();
        this.canvas.resetCards();
        this.expandedNodeIds.set(new Set());
        this.cableHover.clear();
        this.hoveredConnectionId.set(null);
        this.selection.set(null);
    }


    /** Moves the view only when a revealed card is off screen, and then onto it and the card it came from. */
    private bringIntoView(objectIds: number[]): void {
        const nodes = this.nodes();
        const revealed = objectIds
            .map((objectId) => nodes.get(objectId))
            .filter((node): node is CablingNodeLayout => !!node);
        const parents = objectIds
            .map((objectId) => this.store.graph().reveals.get(objectId)?.parentId)
            .map((parentId) => (parentId == null ? undefined : nodes.get(parentId)))
            .filter((node): node is CablingNodeLayout => !!node);

        this.canvas.reveal(cablingBounds(revealed), cablingBounds([...revealed, ...parents]));
    }
}
