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
import { Injectable, computed, effect, inject, signal } from '@angular/core';

import { RackDragSource, RackDropPlan } from '../models/rack-dnd.types';
import { RackArea, RackRowView, RackViewSide } from '../models/rack-overview.types';
import {
    dragHeightOf,
    grabOffsetIn,
    isSamePlacement,
    isSamePlan,
    planAreaDrop,
    planSlotDrop,
    slotAtPoint
} from '../utils/rack-drop-rules';
import { RackOverviewStore } from './rack-overview-store.service';
/* ------------------------------------------------------------------------------------------------------------------ */

/** The areas a row can be dropped into that hold no slots: the two side rails and the staging tray. */
const CARD_AREAS: RackArea[] = [RackArea.LEFT, RackArea.RIGHT, RackArea.UNASSIGNED];


/**
 * One drag gesture, from the plate that was grabbed to the placement that is written.
 *
 * Built on the browser's own drag and drop rather than on pointer events: it brings the drag image,
 * Escape to cancel and edge auto-scrolling with it, all of which a rack that is taller than the screen
 * needs. What it cannot answer is which U the pointer is over, and that is what this adds - measured
 * against the face's own band, never against the U token, because the drawing is zoomable.
 *
 * Provided by the component, so the state belongs to one rack view.
 */
@Injectable()
export class RackDragService {

    private readonly store = inject(RackOverviewStore);

    /** The row being dragged, if any. Set for the length of one gesture and cleared when it ends. */
    private readonly source = signal<RackDragSource | null>(null);

    /**
     * Where the drag currently points. Compared by the placement it describes, not by identity: the
     * browser reports a position on every pixel of the gesture, and only a change of target has to
     * reach the drawing.
     */
    private readonly plan = signal<RackDropPlan | null>(null, { equal: isSamePlan });

    /**
     * Whether the hit area over each face may take the pointer. It must not while the gesture is still
     * being set up: Chromium re-tests what lies under the cursor when it hands the drag to the system,
     * and an area that has just gone live over the grabbed plate is not the plate, so the drag is
     * dropped before it begins. Firefox keeps the gesture it already started, which is why it worked
     * there. Armed on the first dragover of the drawing instead - by then the drag is under way.
     */
    private readonly armed = signal(false);

    public readonly isDragging = computed(() => this.source() !== null);

    /** Read by the hit area of each face, which stays out of the way until the drag is running. */
    public readonly hitAreasLive = this.armed.asReadonly();

    /** The plan as the drawing reads it, so the elevation can preview the U range it would take. */
    public readonly dropPlan = this.plan.asReadonly();

    /** The card the drag currently points at, which is the one that highlights as the target. */
    public readonly targetArea = computed<RackArea | null>(() => {
        const plan = this.plan();

        return plan?.ok && plan.target === 'area' ? plan.area : null;
    });

    /**
     * Every card the row in flight could be dropped into. They advertise themselves while the drag
     * runs, so the way out of the elevation does not have to be guessed at.
     */
    public readonly droppableAreas = computed<ReadonlySet<RackArea>>(() => {
        const source = this.source();

        if (!source) {
            return new Set<RackArea>();
        }

        return new Set(CARD_AREAS.filter(area => planAreaDrop(source, area).ok));
    });

    /* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    constructor() {
        effect(() => {
            this.store.rows();

            /*
             * A dragend is the only thing that ends a gesture, and it is delivered to the element the
             * drag started on - so a reload that replaces that element takes the end of the gesture
             * with it. Left set, the drawing would stay in its dragging state for good, with the hit
             * areas over each face still swallowing every click. Ending here cannot be lost.
             *
             * Free when nothing is in flight: both signals already hold the value being written.
             */
            this.end();
        });
    }

    /* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    public isDragged(mount: RackRowView): boolean {
        return this.source()?.mount.mountId === mount.mountId;
    }

    /* -------------------------------------------------- DRAG SOURCES -------------------------------------------------- */

    /**
     * A mounted row is dragged by its own faceplate, and the U it was grabbed by stays under the cursor
     * while it moves - the same way the row would be carried in a real rack.
     */
    public onPlateDragStart(event: DragEvent, mount: RackRowView): void {
        if (!this.store.canEdit) {
            event.preventDefault();
            return;
        }

        const height = dragHeightOf(mount);
        const plate = (event.currentTarget as HTMLElement).getBoundingClientRect();

        this.start(event, { mount, height, grabOffset: grabOffsetIn(plate, event.clientY, height) });
    }


    /** A card beside the drawing is not drawn to scale, so its row lands with its top U under the cursor. */
    public onCardDragStart(event: DragEvent, mount: RackRowView): void {
        if (!this.store.canEdit) {
            event.preventDefault();
            return;
        }

        this.start(event, { mount, height: dragHeightOf(mount), grabOffset: 0 });
    }


    /** Fires for a completed drop and for a cancelled gesture alike, which is what Escape produces. */
    public onDragEnd(): void {
        this.end();
    }

    /* --------------------------------------------------- DROP TARGETS ------------------------------------------------- */

    /**
     * Any dragover reaching the drawing, delivered by whatever the pointer is actually over - a plate,
     * a free bay, the cavity. It only arms the hit areas of the faces, and takes no drop of its own.
     */
    public onDrawingDragOver(): void {
        if (this.source()) {
            this.armed.set(true);
        }
    }


    public onFaceDragOver(event: DragEvent, side: RackViewSide): void {
        const plan = this.planForFace(event, side);

        if (plan) {
            this.offer(plan, event);
        }
    }


    public onFaceDragLeave(): void {
        this.plan.set(null);
    }


    /**
     * Re-resolved from the drop itself rather than trusting the last hover, so the placement that is
     * written is always the one the pointer was actually over when it was released.
     */
    public onFaceDrop(event: DragEvent, side: RackViewSide): void {
        event.preventDefault();

        const source = this.source();
        const plan = this.planForFace(event, side);

        this.end();
        this.commit(source, plan);
    }


    public onAreaDragOver(event: DragEvent, area: RackArea): void {
        const source = this.source();

        if (source) {
            this.offer(planAreaDrop(source, area), event);
        }
    }


    /** Only a pointer that has left the card counts; moving between its rows must not clear the target. */
    public onAreaDragLeave(event: DragEvent): void {
        const card = event.currentTarget as HTMLElement;

        if (!card.contains(event.relatedTarget as Node | null)) {
            this.plan.set(null);
        }
    }


    public onAreaDrop(event: DragEvent, area: RackArea): void {
        event.preventDefault();

        const source = this.source();
        const plan = source ? planAreaDrop(source, area) : null;

        this.end();
        this.commit(source, plan);
    }

    /* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    private start(event: DragEvent, source: RackDragSource): void {
        this.source.set(source);
        this.plan.set(null);

        if (event.dataTransfer) {
            event.dataTransfer.effectAllowed = 'move';
            // Firefox refuses to start a drag that carries no payload.
            event.dataTransfer.setData('text/plain', String(source.mount.mountId));
        }
    }


    private end(): void {
        this.source.set(null);
        this.plan.set(null);
        this.armed.set(false);
    }


    /** Where the pointer currently points on a face, measured against that face's own slot band. */
    private planForFace(event: DragEvent, side: RackViewSide): RackDropPlan | null {
        const source = this.source();

        if (!source) {
            return null;
        }

        const band = (event.currentTarget as HTMLElement).getBoundingClientRect();
        const slot = slotAtPoint(event.clientY, band, this.store.rackHeight());

        return slot === null ? null : planSlotDrop(source, side, slot, this.store.rows(), this.store.rackHeight());
    }


    /** Shows the plan on the drawing and, when it holds, tells the browser the drop may go ahead. */
    private offer(plan: RackDropPlan, event: DragEvent): void {
        this.plan.set(plan);

        if (!plan.ok) {
            return;
        }

        // Only a prevented dragover accepts a drop.
        event.preventDefault();

        if (event.dataTransfer) {
            event.dataTransfer.dropEffect = 'move';
        }
    }


    private commit(source: RackDragSource | null, plan: RackDropPlan | null): void {
        if (!source || !plan?.ok || isSamePlacement(source, plan)) {
            return;
        }

        // A placement is held across the reload, so the inspector reports where the row ended up.
        // A drop out of the elevation is the row leaving the drawing, and the card goes with it.
        this.store.select(plan.target === 'slot' ? source.mount.mountId : null);
        this.store.updatePlacement(source.mount.mountId, plan.payload);
    }
}
