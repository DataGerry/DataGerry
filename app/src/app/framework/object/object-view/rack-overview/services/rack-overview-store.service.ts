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
import { DestroyRef, Injectable, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { EMPTY, Subject, catchError, finalize, switchMap } from 'rxjs';

import { LoaderService } from 'src/app/core/services/loader.service';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { PermissionService } from 'src/app/modules/auth/services/permission.service';

import {
    RACK_EDIT_RIGHT,
    RackArea,
    RackAreaGroup,
    RackFace,
    RackMountUpdatePayload,
    RackOverviewResponse,
    RackRowView
} from '../models/rack-overview.types';
import {
    buildFace,
    buildSlotTicks,
    collectOutOfRangeMounts,
    fitsRack,
    sortByPosition,
    sortTypeLegend
} from '../utils/rack-layout.util';
import { toOccupantLegendView, toRowViews, toTypeLegendView } from '../utils/rack-row-view.util';
import { RackOverviewService } from './rack-overview.service';
/* ------------------------------------------------------------------------------------------------------------------ */


/**
 * Everything the rack view knows about one rack: the loaded overview, every reading derived from it,
 * which row is selected, and the writes that change any of it.
 *
 * Provided by the component rather than in root, so each rack view owns its own copy and a second one
 * on the page cannot overwrite the first.
 */
@Injectable()
export class RackOverviewStore {

    private readonly rackOverviewService = inject(RackOverviewService);
    private readonly loaderService = inject(LoaderService);
    private readonly toastService = inject(ToastService);
    private readonly permissionService = inject(PermissionService);
    private readonly destroyRef = inject(DestroyRef);

    /** `*permissionLink` only hides the controls, so every write path re-checks the right before it acts. */
    public readonly canEdit = this.permissionService.hasRight(RACK_EDIT_RIGHT)
        || this.permissionService.hasExtendedRight(RACK_EDIT_RIGHT);

    public readonly isLoading$ = this.loaderService.isLoading$;
    public readonly hasError = signal(false);

    /** The rack being shown. Held so a write knows which rack to address without being told again. */
    private readonly openRackId = signal<number | null>(null);

    public readonly rackId = this.openRackId.asReadonly();

    /** The response as it came back. Everything the view draws is derived from this one signal. */
    private readonly overview = signal<RackOverviewResponse | null>(null);

    /**
     * The selection is held as an id rather than as the row itself: a reload replaces every row object,
     * and an id survives that without having to match the old object against the new list.
     */
    private readonly selectedMountId = signal<number | null>(null);

    /**
     * Every request to re-read the rack. Routed through one stream so a newer read cancels the one
     * before it: a drag makes writes cheap enough to fire several in a second, and two overlapping
     * reads can otherwise answer out of order and leave the drawing showing the older of the two.
     */
    private readonly reloads = new Subject<void>();

    public readonly rack = computed(() => this.overview()?.rack ?? null);

    public readonly rackHeight = computed(() => this.rack()?.height ?? 0);

    /** Every row of the rack, drawn-ready. One mapping pass feeds the elevation, the rails and the tray. */
    public readonly rows = computed<RackRowView[]>(() => {
        const areas = this.overview()?.areas;

        return areas ? toRowViews(Object.values(areas).flat(), this.rackHeight()) : [];
    });

    public readonly selectedRow = computed<RackRowView | null>(() => {
        const mountId = this.selectedMountId();

        return mountId === null ? null : this.rows().find(row => row.mountId === mountId) ?? null;
    });

    public readonly typesLegend = computed(() =>
        sortTypeLegend(this.overview()?.types_legend ?? []).map(toTypeLegendView));

    public readonly occupantsLegend = computed(() =>
        (this.overview()?.occupants_legend ?? []).map(toOccupantLegendView));

    /**
     * Both faces are assembled up front, so switching the view is a template change rather than a
     * rebuild. A FULL_DEPTH row holds the same slots front and back, and the backend reports it once,
     * so it is handed to both faces.
     */
    public readonly frontFace = computed<RackFace>(() =>
        buildFace(RackArea.FRONT, 'Front', [...this.rowsOf(RackArea.FRONT), ...this.fullDepthRows()], this.rackHeight()));

    public readonly rearFace = computed<RackFace>(() =>
        buildFace(RackArea.BACK, 'Rear', [...this.rowsOf(RackArea.BACK), ...this.fullDepthRows()], this.rackHeight()));

    /** The rows that hold both faces at once; drawn in each cabinet and linked across the ruler. */
    public readonly bridges = computed(() =>
        this.fullDepthRows().filter(row => fitsRack(row, this.rackHeight())));

    public readonly outOfRangeRows = computed(() => collectOutOfRangeMounts(
        [...this.rowsOf(RackArea.FRONT), ...this.fullDepthRows(), ...this.rowsOf(RackArea.BACK)],
        this.rackHeight()
    ));

    public readonly sideRails = computed<RackAreaGroup[]>(() => [
        { area: RackArea.LEFT, title: 'Left side', mounts: sortByPosition(this.rowsOf(RackArea.LEFT)) },
        { area: RackArea.RIGHT, title: 'Right side', mounts: sortByPosition(this.rowsOf(RackArea.RIGHT)) }
    ]);

    public readonly unassignedGroup = computed<RackAreaGroup>(() => ({
        area: RackArea.UNASSIGNED,
        title: 'In the rack, not placed',
        mounts: sortByPosition(this.rowsOf(RackArea.UNASSIGNED))
    }));

    /** The U ruler, top down. */
    public readonly slotTicks = computed(() => buildSlotTicks(this.rackHeight()));

    /** The grid's row track list: the cap, one track per U, then the plinth. */
    public readonly rowTemplate = computed(() => {
        const rackHeight = this.rackHeight();

        // repeat() needs a positive count, so a rack without a height falls back to a single track.
        return rackHeight > 0
            ? `var(--rack-cap) repeat(${rackHeight}, var(--rack-u)) var(--rack-plinth)`
            : 'var(--rack-cap) minmax(6rem, auto) var(--rack-plinth)';
    });

    /* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    constructor() {
        this.reloads
            .pipe(
                switchMap(() => {
                    this.loaderService.show();

                    return this.rackOverviewService.getOverview(this.rackId()).pipe(
                        // Reported here rather than in the subscriber: an error reaching the outer
                        // stream would end it, and no later reload would have anything left to run on.
                        catchError((err) => {
                            this.hasError.set(true);
                            this.toastService.error(err?.error?.message);

                            return EMPTY;
                        }),
                        finalize(() => this.loaderService.hide())
                    );
                }),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe((response) => {
                this.overview.set(response ?? null);
                this.hasError.set(false);
            });
    }

    /* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    /** Points the store at a rack and reads it. A null id simply leaves the view with nothing to draw. */
    public open(rackId: number | null): void {
        this.openRackId.set(rackId);
        this.selectedMountId.set(null);
        // Cleared up front, so a rack that failed to load does not report its error over the next one.
        this.hasError.set(false);

        if (rackId != null) {
            this.reload();
        }
    }


    public reload(): void {
        this.reloads.next();
    }


    public isSelected(mount: RackRowView): boolean {
        return this.selectedMountId() === mount.mountId;
    }


    public toggleSelection(mount: RackRowView): void {
        this.selectedMountId.update(current => current === mount.mountId ? null : mount.mountId);
    }


    public select(mountId: number | null): void {
        this.selectedMountId.set(mountId);
    }


    /**
     * Writes a placement and redraws from the answer. The rack is not moved optimistically: the
     * backend owns the overlap rules, and a refused move has to leave the drawing as it was.
     */
    public updatePlacement(mountId: number, payload: RackMountUpdatePayload): void {
        if (!this.canEdit) {
            return;
        }

        this.loaderService.show();

        this.rackOverviewService
            .updateMount(this.rackId(), mountId, payload)
            .pipe(takeUntilDestroyed(this.destroyRef), finalize(() => this.loaderService.hide()))
            .subscribe({
                next: () => this.reload(),
                error: (err) => this.toastService.error(err?.error?.message)
            });
    }


    /** Removes the membership only. The mounted object itself is never touched. */
    public removeMount(mountId: number): void {
        if (!this.canEdit) {
            return;
        }

        this.loaderService.show();

        this.rackOverviewService
            .deleteMount(this.rackId(), mountId)
            .pipe(takeUntilDestroyed(this.destroyRef), finalize(() => this.loaderService.hide()))
            .subscribe({
                next: () => {
                    this.selectedMountId.set(null);
                    this.reload();
                },
                error: (err) => this.toastService.error(err?.error?.message)
            });
    }

    /* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    private rowsOf(area: RackArea): RackRowView[] {
        return this.rows().filter(row => row.area === area);
    }


    private fullDepthRows(): RackRowView[] {
        return this.rowsOf(RackArea.FULL_DEPTH);
    }
}
