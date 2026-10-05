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
import { AsyncPipe } from '@angular/common';
import {
    ChangeDetectionStrategy,
    Component,
    ElementRef,
    computed,
    inject,
    input,
    signal,
    viewChild
} from '@angular/core';
import { takeUntilDestroyed, toObservable, toSignal } from '@angular/core/rxjs-interop';
import { FormControl, FormGroup, ReactiveFormsModule } from '@angular/forms';

import { CoreModule } from 'src/app/core/core.module';
import { LoaderService } from 'src/app/core/services/loader.service';
import { CablingNodeComponent } from './components/cabling-node/cabling-node.component';
import {
    CABLE_CASING_STROKE,
    CABLING_GEOMETRY,
    CABLING_PAN_STEP,
    CABLING_ZOOM,
    DEFAULT_DISPLAY_OPTIONS
} from './constants/cabling.constants';
import { CablingGesture, CablingSize, CablingViewport } from './models/cabling-viewport.types';
import { CablingDisplayOptions, CablingNodeLayout, CablingPoint } from './models/cabling.types';
import { CablingViewStore } from './services/cabling-view.store';
import {
    cablingBounds,
    layoutCablingEdges,
    layoutCablingNodes,
    offsetCablingNodes
} from './utils/cabling-layout.util';
import {
    centerViewport,
    containsBounds,
    fitViewport,
    visibleCanvas,
    zoomAround
} from './utils/cabling-viewport.util';
/* ------------------------------------------------------------------------------------------------------------------ */

/** A press on one of these belongs to the control, not to a pan or a drag. */
const INTERACTIVE_SELECTOR = 'a, button, input, label, select, textarea';

/** How far one notch of Ctrl + wheel zooms; pixel deltas are small, line deltas are scaled up. */
const WHEEL_ZOOM_RATE = 0.002;
const WHEEL_LINE_HEIGHT = 16;

/** Screen pixels a press may travel and still count as a click. */
const DRAG_THRESHOLD = 4;


/**
 * The cabling of one object as a graph: the object, the objects its cables reach, and the cables
 * between their ports. Following a port outwards adds the object at its far end.
 */
@Component({
    selector: 'cmdb-cabling-view',
    standalone: true,
    imports: [AsyncPipe, ReactiveFormsModule, CoreModule, CablingNodeComponent],
    templateUrl: './cabling-view.component.html',
    styleUrls: ['./cabling-view.component.scss'],
    providers: [CablingViewStore],
    changeDetection: ChangeDetectionStrategy.OnPush
})
export class CablingViewComponent {

    public readonly objectId = input<number | null>(null);

    protected readonly store = inject(CablingViewStore);
    private readonly loaderService = inject(LoaderService);

    public readonly isLoading$ = this.loaderService.isLoading$;

    public readonly viewport = signal<CablingViewport>({ x: 0, y: 0, zoom: 1 });
    public readonly hoveredConnectionId = signal<number | null>(null);
    public readonly selectedConnectionId = signal<number | null>(null);
    public readonly isPanning = signal(false);
    public readonly animate = signal(false);

    private readonly expandedNodeIds = signal<ReadonlySet<number>>(new Set());
    private readonly offsets = signal<ReadonlyMap<number, CablingPoint>>(new Map());

    public readonly displayForm = new FormGroup({
        showFreePorts: new FormControl(false, { nonNullable: true })
    });

    private readonly showFreePorts = toSignal(this.displayForm.controls.showFreePorts.valueChanges, { initialValue: false });

    public readonly options = computed<CablingDisplayOptions>(() => ({
        ...DEFAULT_DISPLAY_OPTIONS,
        onlyConnected: !this.showFreePorts()
    }));

    /** Laid out apart from the drag offsets, so moving one card does not re-run the placement. */
    private readonly placedNodes = computed(() =>
        layoutCablingNodes(this.store.graph(), this.options(), this.expandedNodeIds()));

    public readonly nodes = computed(() => offsetCablingNodes(this.placedNodes(), this.offsets()));
    public readonly nodeList = computed(() => [...this.nodes().values()]);
    public readonly edges = computed(() => layoutCablingEdges(this.nodes(), this.store.graph().edges.values()));
    public readonly bounds = computed(() => cablingBounds(this.nodeList()));
    public readonly highlightedConnectionId = computed(() => this.selectedConnectionId() ?? this.hoveredConnectionId());

    /** Drawn a second time above the cards, so a cable running behind one can be followed. */
    public readonly selectedEdge = computed(() => {
        const connectionId = this.selectedConnectionId();

        return connectionId == null ? null : (this.edges().find((edge) => edge.connectionId === connectionId) ?? null);
    });
    public readonly isEmpty = computed(() => this.store.loaded() && !this.edges().length);

    public readonly transform = computed(() => {
        const { x, y, zoom } = this.viewport();

        return `translate(${ x }px, ${ y }px) scale(${ zoom })`;
    });

    public readonly casingStroke = CABLE_CASING_STROKE;
    public readonly endDotRadius = CABLING_GEOMETRY.endDotRadius;

    /** Not named `viewport`: a template reference of that name would shadow the signal in the template. */
    private readonly viewportRef = viewChild.required<ElementRef<HTMLElement>>('canvasFrame');
    private gesture: CablingGesture | null = null;

    /** Set when a press ended as a pan or a drag, so the click that follows it selects nothing. */
    private gestureMoved = false;

    private readonly keyActions: Readonly<Record<string, () => void>> = {
        '+': () => this.zoomIn(),
        '=': () => this.zoomIn(),
        '-': () => this.zoomOut(),
        '_': () => this.zoomOut(),
        '0': () => this.fitToView(),
        'Escape': () => this.selectedConnectionId.set(null),
        'ArrowLeft': () => this.panBy(CABLING_PAN_STEP, 0),
        'ArrowRight': () => this.panBy(-CABLING_PAN_STEP, 0),
        'ArrowUp': () => this.panBy(0, CABLING_PAN_STEP),
        'ArrowDown': () => this.panBy(0, -CABLING_PAN_STEP)
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
            .subscribe(() => this.fitToView(false));

        this.store.revealed$
            .pipe(takeUntilDestroyed())
            .subscribe((objectIds) => this.bringIntoView(objectIds));
    }

/* ---------------------------------------------------- EVENTS ------------------------------------------------------ */

    public onPointerDown(event: PointerEvent): void {
        const target = event.target as Element | null;

        if (event.button !== 0 || this.gesture || target?.closest(INTERACTIVE_SELECTOR)) {
            return;
        }

        const card = target?.closest<HTMLElement>('[data-object-id]');
        const objectId = card ? Number(card.dataset['objectId']) : NaN;
        const isNode = Number.isFinite(objectId);
        const { x, y } = this.viewport();

        this.gestureMoved = false;
        this.gesture = {
            kind: isNode ? 'node' : 'pan',
            pointerId: event.pointerId,
            objectId: isNode ? objectId : null,
            startX: event.clientX,
            startY: event.clientY,
            origin: isNode ? (this.offsets().get(objectId) ?? { x: 0, y: 0 }) : { x, y },
            moved: false
        };
    }


    public onPointerMove(event: PointerEvent): void {
        const gesture = this.gesture;

        if (!gesture || gesture.pointerId !== event.pointerId) {
            return;
        }

        const dx = event.clientX - gesture.startX;
        const dy = event.clientY - gesture.startY;

        // Captured only once it moves: a captured pointer's click lands on the canvas, not the port.
        if (!gesture.moved) {
            if (Math.hypot(dx, dy) < DRAG_THRESHOLD) {
                return;
            }

            gesture.moved = true;
            this.animate.set(false);
            this.isPanning.set(true);

            try {
                (event.currentTarget as HTMLElement | null)?.setPointerCapture?.(event.pointerId);
            } catch {
                // A pointer that is no longer active cannot be captured; the gesture still follows it.
            }
        }

        if (gesture.kind === 'pan') {
            this.viewport.update((viewport) => ({ ...viewport, x: gesture.origin.x + dx, y: gesture.origin.y + dy }));
            return;
        }

        // A card moves in canvas units, so the pointer's screen distance is scaled back by the zoom.
        const zoom = this.viewport().zoom;
        this.offsets.update((offsets) => new Map(offsets).set(gesture.objectId, {
            x: gesture.origin.x + dx / zoom,
            y: gesture.origin.y + dy / zoom
        }));
    }


    public onPointerUp(event: PointerEvent): void {
        if (!this.gesture || this.gesture.pointerId !== event.pointerId) {
            return;
        }

        const element = event.currentTarget as HTMLElement | null;

        if (element?.hasPointerCapture?.(event.pointerId)) {
            element.releasePointerCapture(event.pointerId);
        }

        this.gestureMoved = this.gesture.moved;
        this.gesture = null;
        this.isPanning.set(false);
    }


    /** A second click on the same cable puts it back behind the cards. */
    public onSelectConnection(connectionId: number): void {
        if (!this.gestureMoved) {
            this.selectedConnectionId.update((selected) => (selected === connectionId ? null : connectionId));
        }
    }


    /** A click anywhere but a cable or a cabled port drops the selection. */
    public onCanvasClick(event: MouseEvent): void {
        const moved = this.gestureMoved;
        this.gestureMoved = false;

        if (moved || (event.target as Element | null)?.closest('.cabling-edge__hit, .cabling-port.is-cabled')) {
            return;
        }

        this.selectedConnectionId.set(null);
    }


    /** Only Ctrl or Cmd + wheel zooms (a pinch reports as that too); a plain wheel keeps scrolling the page. */
    public onWheel(event: WheelEvent): void {
        if (!event.ctrlKey && !event.metaKey) {
            return;
        }

        event.preventDefault();

        const rect = this.viewportRef().nativeElement.getBoundingClientRect();
        const delta = event.deltaMode === WheelEvent.DOM_DELTA_LINE ? event.deltaY * WHEEL_LINE_HEIGHT : event.deltaY;

        this.animate.set(false);
        this.viewport.update((viewport) => zoomAround(
            viewport,
            viewport.zoom * Math.exp(-delta * WHEEL_ZOOM_RATE),
            { x: event.clientX - rect.left, y: event.clientY - rect.top }
        ));
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

    public zoomIn(): void {
        this.zoomBy(CABLING_ZOOM.step);
    }


    public zoomOut(): void {
        this.zoomBy(1 / CABLING_ZOOM.step);
    }


    public fitToView(animate = true): void {
        this.animate.set(animate);
        this.viewport.set(fitViewport(this.bounds(), this.measure(), this.viewport()));
    }


    public centerOn(point: CablingPoint): void {
        this.animate.set(true);
        this.viewport.set(centerViewport(point, this.measure(), this.viewport().zoom));
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
        this.offsets.set(new Map());
        this.expandedNodeIds.set(new Set());
        this.hoveredConnectionId.set(null);
        this.selectedConnectionId.set(null);
    }


    private zoomBy(factor: number): void {
        const size = this.measure();

        this.animate.set(true);
        this.viewport.update((viewport) => zoomAround(
            viewport,
            viewport.zoom * factor,
            { x: size.width / 2, y: size.height / 2 }
        ));
    }


    private panBy(dx: number, dy: number): void {
        this.animate.set(true);
        this.viewport.update((viewport) => ({ ...viewport, x: viewport.x + dx, y: viewport.y + dy }));
    }


    /** Moves the view only when a revealed card is off screen, and then onto it and the card it came from. */
    private bringIntoView(objectIds: number[]): void {
        const nodes = this.nodes();
        const revealed = objectIds.map((objectId) => nodes.get(objectId)).filter((node): node is CablingNodeLayout => !!node);
        const target = cablingBounds(revealed);

        if (!target || containsBounds(visibleCanvas(this.viewport(), this.measure()), target)) {
            return;
        }

        const parents = objectIds
            .map((objectId) => this.store.graph().reveals.get(objectId)?.parentId)
            .map((parentId) => (parentId == null ? undefined : nodes.get(parentId)))
            .filter((node): node is CablingNodeLayout => !!node);
        const focus = cablingBounds([...revealed, ...parents]);

        this.centerOn({ x: (focus.minX + focus.maxX) / 2, y: (focus.minY + focus.maxY) / 2 });
    }


    private measure(): CablingSize {
        const rect = this.viewportRef().nativeElement.getBoundingClientRect();

        return { width: rect.width, height: rect.height };
    }
}
