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
import { ChangeDetectionStrategy, Component, DestroyRef, computed, inject, input, signal } from '@angular/core';
import { takeUntilDestroyed, toObservable } from '@angular/core/rxjs-interop';
import { Router } from '@angular/router';
import { NgbModal } from '@ng-bootstrap/ng-bootstrap';
import { finalize } from 'rxjs';

import { DeleteModalService } from 'src/app/core/services/delete-modal.service';
import { FullscreenModalService } from 'src/app/core/services/fullscreen-modal.service';
import { LoaderService } from 'src/app/core/services/loader.service';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { PermissionService } from 'src/app/modules/auth/services/permission.service';

import { RackMountModalComponent } from './components/rack-mount-modal/rack-mount-modal.component';
import {
    RACK_EDIT_RIGHT,
    RackArea,
    RackAreaGroup,
    RackFace,
    RackMountRow,
    RackOverviewResponse,
    RackRowView,
    RackViewMode,
    RackViewSide
} from './models/rack-overview.types';
import { RackOverviewService } from './services/rack-overview.service';
import {
    buildFace,
    buildSlotTicks,
    collectOutOfRangeMounts,
    fitsRack,
    sortByPosition,
    sortTypeLegend
} from './utils/rack-layout.util';
import { toOccupantLegendView, toRowViews, toTypeLegendView } from './utils/rack-row-view.util';
/* ------------------------------------------------------------------------------------------------------------------ */

/**
 * How many type entries the legend shows before it has to be expanded. A rack may hold dozens of types,
 * and the key must not grow taller than the drawing it explains.
 */
const LEGEND_TYPE_LIMIT = 6;

/**
 * Zoom bounds for the drawing, in percent. The range leans on shrinking: a rack is taller than the
 * screen far more often than it is too small to read.
 */
const ZOOM_MIN = 80;
const ZOOM_MAX = 150;
const ZOOM_STEP = 10;
const ZOOM_DEFAULT = 100;


@Component({
    selector: 'cmdb-rack-overview',
    templateUrl: './rack-overview.component.html',
    styleUrls: ['./rack-overview.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    standalone: false
})
export class RackOverviewComponent {

    private readonly rackOverviewService = inject(RackOverviewService);
    private readonly loaderService = inject(LoaderService);
    private readonly toastService = inject(ToastService);
    private readonly deleteModalService = inject(DeleteModalService);
    private readonly fullscreenModalService = inject(FullscreenModalService);
    private readonly modalService = inject(NgbModal);
    private readonly router = inject(Router);
    private readonly permissionService = inject(PermissionService);
    private readonly destroyRef = inject(DestroyRef);

    /**
     * Nullable rather than required: the host binds the id of the object it is still loading, and a
     * required input would throw on the first pass instead of simply having nothing to draw yet.
     */
    public readonly publicId = input<number | null>(null);

    public readonly AREAS = RackArea;
    public readonly isLoading$ = this.loaderService.isLoading$;

    /** `*permissionLink` only hides the controls, so every write path re-checks the right before it acts. */
    public readonly canEdit = this.permissionService.hasRight(RACK_EDIT_RIGHT)
        || this.permissionService.hasExtendedRight(RACK_EDIT_RIGHT);

    /** The response as it came back. Everything the view draws is derived from this one signal. */
    private readonly overview = signal<RackOverviewResponse | null>(null);

    public readonly hasError = signal(false);
    public readonly viewMode = signal<RackViewMode>('split');
    /** Scales the drawing only; the toolbar, the legend and the side column keep their own size. */
    public readonly zoomPercent = signal(ZOOM_DEFAULT);
    public readonly isFullscreen = signal(false);
    /** Only the first types are keyed until the user asks for the rest. */
    public readonly isLegendExpanded = signal(false);

    /**
     * The selection is held as an id rather than as the row itself: a reload replaces every row object,
     * and an id survives that without having to match the old object against the new list.
     */
    private readonly selectedMountId = signal<number | null>(null);

    public readonly rack = computed(() => this.overview()?.rack ?? null);

    public readonly typesLegend = computed(() =>
        sortTypeLegend(this.overview()?.types_legend ?? []).map(toTypeLegendView));

    public readonly occupantsLegend = computed(() =>
        (this.overview()?.occupants_legend ?? []).map(toOccupantLegendView));

    public readonly hasLegend = computed(() => this.typesLegend().length > 0 || this.occupantsLegend().length > 0);

    public readonly visibleTypesLegend = computed(() =>
        this.isLegendExpanded() ? this.typesLegend() : this.typesLegend().slice(0, LEGEND_TYPE_LIMIT));

    public readonly hiddenTypesCount = computed(() => Math.max(this.typesLegend().length - LEGEND_TYPE_LIMIT, 0));

    /** Every row of the rack, drawn-ready. One mapping pass feeds the elevation, the rails and the tray. */
    private readonly rows = computed<RackRowView[]>(() => {
        const areas = this.overview()?.areas;

        return areas ? toRowViews(Object.values(areas).flat(), this.rackHeight()) : [];
    });

    public readonly selectedRow = computed<RackRowView | null>(() => {
        const mountId = this.selectedMountId();

        return mountId === null ? null : this.rows().find(row => row.mountId === mountId) ?? null;
    });

    /**
     * Both faces are assembled up front, so switching the view is a template change rather than a
     * rebuild. A FULL_DEPTH row holds the same slots front and back, and the backend reports it once,
     * so it is handed to both faces.
     */
    public readonly frontFace = computed<RackFace>(() =>
        buildFace(RackArea.FRONT, 'Front', [...this.rowsOf(RackArea.FRONT), ...this.fullDepthRows()], this.rackHeight()));

    public readonly rearFace = computed<RackFace>(() =>
        buildFace(RackArea.BACK, 'Rear', [...this.rowsOf(RackArea.BACK), ...this.fullDepthRows()], this.rackHeight()));

    public readonly shownFace = computed(() => this.viewMode() === 'rear' ? this.rearFace() : this.frontFace());

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

    /** The face a single-face view is showing, and the face a new row defaults to in a split view. */
    public readonly defaultSide = computed<RackViewSide>(() =>
        this.viewMode() === 'rear' ? RackArea.BACK : RackArea.FRONT);

    /** Also the value the board is zoomed by, so the read-out and the drawing cannot drift apart. */
    public readonly zoomLabel = computed(() => `${this.zoomPercent()}%`);

    public readonly canZoomIn = computed(() => this.zoomPercent() < ZOOM_MAX);

    public readonly canZoomOut = computed(() => this.zoomPercent() > ZOOM_MIN);

    public readonly isDefaultZoom = computed(() => this.zoomPercent() === ZOOM_DEFAULT);

    /**
     * A fullscreen element is the only thing painted, so a tooltip parked on the body would never be
     * seen. While fullscreen is open they render next to their trigger instead.
     */
    public readonly tooltipContainer = computed<string | null>(() => this.isFullscreen() ? null : 'body');

    private readonly rackHeight = computed(() => this.rack()?.height ?? 0);

    /* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    constructor() {
        // Emits the first value as well, so this is also what loads the rack the view opens on.
        toObservable(this.publicId)
            .pipe(takeUntilDestroyed())
            .subscribe((rackId) => {
                this.viewMode.set('split');
                this.selectedMountId.set(null);
                this.isLegendExpanded.set(false);

                if (rackId != null) {
                    this.loadOverview();
                }
            });
    }

    /* ---------------------------------------------------- EVENTS ------------------------------------------------------ */

    public onViewChange(mode: RackViewMode): void {
        this.viewMode.set(mode);
    }

    public onZoomIn(): void {
        this.setZoom(this.zoomPercent() + ZOOM_STEP);
    }

    public onZoomOut(): void {
        this.setZoom(this.zoomPercent() - ZOOM_STEP);
    }

    public onResetZoom(): void {
        this.setZoom(ZOOM_DEFAULT);
    }

    /** Driven by the directive, so leaving fullscreen with Escape keeps the button in step. */
    public onFullscreenChange(isFullscreen: boolean): void {
        this.isFullscreen.set(isFullscreen);
    }

    public onToggleLegend(): void {
        this.isLegendExpanded.update(expanded => !expanded);
    }

    public onAddToRack(): void {
        this.openMountModal(null, this.defaultSide(), null);
    }

    /** Adding straight into one of the areas without slot geometry. */
    public onAddToArea(area: RackArea): void {
        this.openMountModal(null, area, null);
    }

    /** Filling the clicked slot on the clicked face, pre-filled with that slot as the anchor. */
    public onFreeSlotClick(side: RackViewSide, slot: number): void {
        this.openMountModal(null, side, slot);
    }

    public onSelectMount(mount: RackRowView): void {
        this.selectedMountId.update(current => current === mount.mountId ? null : mount.mountId);
    }

    public onClearSelection(): void {
        this.selectedMountId.set(null);
    }

    public onEditMount(mount: RackRowView): void {
        this.openMountModal(mount.row, mount.area, mount.startSlot);
    }

    /** Frees the slots but keeps the row in the rack, so it can be placed again later. */
    public onUnplaceMount(mount: RackRowView): void {
        if (!this.canEdit) {
            return;
        }

        this.loaderService.show();

        this.rackOverviewService
            .updateMount(this.publicId(), mount.mountId, { area: RackArea.UNASSIGNED })
            .pipe(takeUntilDestroyed(this.destroyRef), finalize(() => this.loaderService.hide()))
            .subscribe({
                next: () => this.loadOverview(),
                error: (err) => this.toastService.error(err?.error?.message)
            });
    }

    public onRemoveMount(mount: RackRowView): void {
        if (!this.canEdit) {
            return;
        }

        this.deleteModalService.confirmDelete({
            title: 'Remove from rack',
            itemType: mount.kindTitle,
            itemName: mount.label,
            description: mount.isMount
                ? 'The object leaves the rack. The object itself is not deleted.'
                : 'The slots it holds become free again.',
            onConfirm: () => this.deleteMount(mount)
        });
    }

    /** Only a mount has an object to open; an occupant row never reaches this. */
    public onOpenObject(objectId: number | null): void {
        if (objectId == null) {
            return;
        }

        this.router.navigate([`/framework/object/view/${objectId}`]);
    }

    /* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    public isSelected(mount: RackRowView): boolean {
        return this.selectedMountId() === mount.mountId;
    }

    /* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    private rowsOf(area: RackArea): RackRowView[] {
        return this.rows().filter(row => row.area === area);
    }

    private fullDepthRows(): RackRowView[] {
        return this.rowsOf(RackArea.FULL_DEPTH);
    }

    private setZoom(percent: number): void {
        this.zoomPercent.set(Math.min(Math.max(percent, ZOOM_MIN), ZOOM_MAX));
    }

    private loadOverview(): void {
        this.loaderService.show();

        this.rackOverviewService
            .getOverview(this.publicId())
            .pipe(takeUntilDestroyed(this.destroyRef), finalize(() => this.loaderService.hide()))
            .subscribe({
                next: (response) => {
                    this.overview.set(response ?? null);
                    this.hasError.set(false);
                },
                error: (err) => {
                    this.hasError.set(true);
                    this.toastService.error(err?.error?.message);
                }
            });
    }

    private openMountModal(mount: RackMountRow | null, presetArea: RackArea, presetStartSlot: number | null): void {
        if (!this.canEdit) {
            return;
        }

        // Opened through the fullscreen service: a modal parked on the body is not painted over a
        // fullscreen element, so it has to be hosted inside the rack view while that is open.
        const modalRef = this.fullscreenModalService.open(this.modalService, RackMountModalComponent, {
            size: 'lg',
            windowClass: 'dg-modal-window',
            backdropClass: 'dg-modal-window-backdrop'
        });

        modalRef.componentInstance.rackId = this.publicId();
        modalRef.componentInstance.rackHeight = this.rackHeight();
        modalRef.componentInstance.mount = mount;
        modalRef.componentInstance.presetArea = presetArea;
        modalRef.componentInstance.presetStartSlot = presetStartSlot;

        modalRef.result.then(
            (saved) => {
                if (saved) {
                    this.loadOverview();
                }
            },
            () => undefined
        );
    }

    private deleteMount(mount: RackRowView): void {
        this.loaderService.show();

        this.rackOverviewService
            .deleteMount(this.publicId(), mount.mountId)
            .pipe(takeUntilDestroyed(this.destroyRef), finalize(() => this.loaderService.hide()))
            .subscribe({
                next: () => {
                    this.selectedMountId.set(null);
                    this.loadOverview();
                },
                error: (err) => this.toastService.error(err?.error?.message)
            });
    }
}
