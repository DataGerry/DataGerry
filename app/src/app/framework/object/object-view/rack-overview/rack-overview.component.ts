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
import {
    ChangeDetectionStrategy,
    ChangeDetectorRef,
    Component,
    inject,
    Input,
    OnChanges,
    OnDestroy,
    SimpleChanges
} from '@angular/core';
import { Router } from '@angular/router';
import { NgbModal } from '@ng-bootstrap/ng-bootstrap';
import { Subject, finalize, takeUntil } from 'rxjs';

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
    RackHeader,
    RackMountKind,
    RackMountRow,
    RackOccupantLegendEntry,
    RackOverviewResponse,
    RackTypeLegendEntry,
    RackViewMode,
    RackViewSide,
    kindOf,
    toDayString
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
import { RACK_KIND_ICONS, RACK_KIND_LABELS, accentTint, safeAccent, safeIcon } from './utils/rack-visual.util';
/* ------------------------------------------------------------------------------------------------------------------ */

/** Opacity of the row colour behind an icon chip or a side card. */
const TONE_TINT_ALPHA = 0.14;

/** Row 1 of the elevation grid is the cabinet cap, so U numbering starts on row 2. */
const FIRST_SLOT_ROW = 2;

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
export class RackOverviewComponent implements OnChanges, OnDestroy {

    private readonly rackOverviewService = inject(RackOverviewService);
    private readonly loaderService = inject(LoaderService);
    private readonly toastService = inject(ToastService);
    private readonly deleteModalService = inject(DeleteModalService);
    private readonly fullscreenModalService = inject(FullscreenModalService);
    private readonly modalService = inject(NgbModal);
    private readonly router = inject(Router);
    private readonly permissionService = inject(PermissionService);
    private readonly changesRef = inject(ChangeDetectorRef);

    @Input() public publicId: number | null = null;

    public readonly AREAS = RackArea;
    public readonly isLoading$ = this.loaderService.isLoading$;

    /** `*permissionLink` only hides the controls, so every write path re-checks the right before it acts. */
    public readonly canEdit = this.permissionService.hasRight(RACK_EDIT_RIGHT)
        || this.permissionService.hasExtendedRight(RACK_EDIT_RIGHT);

    public rack: RackHeader | null = null;
    public typesLegend: RackTypeLegendEntry[] = [];
    public occupantsLegend: RackOccupantLegendEntry[] = [];
    /** Only the first types are keyed until the user asks for the rest. */
    public isLegendExpanded = false;
    public hasError = false;

    public viewMode: RackViewMode = 'split';
    /** Scales the drawing only; the toolbar, the legend and the inspector keep their own size. */
    public zoomPercent = ZOOM_DEFAULT;
    public isFullscreen = false;
    public frontFace: RackFace | null = null;
    public rearFace: RackFace | null = null;
    /** Both faces in drawing order, so the capacity meters iterate a stable array. */
    public faces: RackFace[] = [];
    /** The rows that hold both faces at once; drawn in each cabinet and linked across the ruler. */
    public bridges: RackMountRow[] = [];
    public outOfRangeMounts: RackMountRow[] = [];
    public sideRails: RackAreaGroup[] = [];
    public unassignedGroup: RackAreaGroup | null = null;
    public slotTicks: number[] = [];
    /** The grid's row track list: the cap, one track per U, then the plinth. */
    public rowTemplate = '';
    public selectedMount: RackMountRow | null = null;

    private overview: RackOverviewResponse | null = null;
    private readonly destroy$ = new Subject<void>();

    /* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    public ngOnChanges(changes: SimpleChanges): void {
        if (changes['publicId'] && this.publicId != null) {
            this.viewMode = 'split';
            this.selectedMount = null;
            this.isLegendExpanded = false;
            this.loadOverview();
        }
    }

    public ngOnDestroy(): void {
        this.destroy$.next();
        this.destroy$.complete();
    }

    /* ---------------------------------------------------- EVENTS ------------------------------------------------------ */

    public onViewChange(mode: RackViewMode): void {
        if (mode === this.viewMode) {
            return;
        }

        this.viewMode = mode;
        this.changesRef.markForCheck();
    }

    public onZoomIn(): void {
        this.setZoom(this.zoomPercent + ZOOM_STEP);
    }

    public onZoomOut(): void {
        this.setZoom(this.zoomPercent - ZOOM_STEP);
    }

    public onResetZoom(): void {
        this.setZoom(ZOOM_DEFAULT);
    }

    /** Driven by the directive, so leaving fullscreen with Escape keeps the button in step. */
    public onFullscreenChange(isFullscreen: boolean): void {
        this.isFullscreen = isFullscreen;
        this.changesRef.markForCheck();
    }

    public onToggleLegend(): void {
        this.isLegendExpanded = !this.isLegendExpanded;
        this.changesRef.markForCheck();
    }

    public onAddToRack(): void {
        this.openMountModal(null, this.defaultSide, null);
    }

    /** Adding straight into one of the areas without slot geometry. */
    public onAddToArea(area: RackArea): void {
        this.openMountModal(null, area, null);
    }

    /** Filling the clicked slot on the clicked face, pre-filled with that slot as the anchor. */
    public onFreeSlotClick(side: RackViewSide, slot: number): void {
        this.openMountModal(null, side, slot);
    }

    public onSelectMount(mount: RackMountRow): void {
        this.selectedMount = this.isSelected(mount) ? null : mount;
        this.changesRef.markForCheck();
    }

    public onClearSelection(): void {
        this.selectedMount = null;
        this.changesRef.markForCheck();
    }

    public onEditMount(mount: RackMountRow): void {
        this.openMountModal(mount, mount.area, mount.start_slot);
    }

    /** Frees the slots but keeps the row in the rack, so it can be placed again later. */
    public onUnplaceMount(mount: RackMountRow): void {
        if (!this.canEdit) {
            return;
        }

        this.loaderService.show();

        this.rackOverviewService
            .updateMount(this.publicId, mount.mount_id, { area: RackArea.UNASSIGNED })
            .pipe(takeUntil(this.destroy$), finalize(() => this.loaderService.hide()))
            .subscribe({
                next: () => this.loadOverview(),
                error: (err) => this.toastService.error(err?.error?.message)
            });
    }

    public onRemoveMount(mount: RackMountRow): void {
        if (!this.canEdit) {
            return;
        }

        this.deleteModalService.confirmDelete({
            title: 'Remove from rack',
            itemType: this.kindTitleOf(mount),
            itemName: this.labelOf(mount),
            description: this.isMount(mount)
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

    /** The face a single-face view is showing, and the face a new row defaults to in a split view. */
    public get defaultSide(): RackViewSide {
        return this.viewMode === 'rear' ? RackArea.BACK : RackArea.FRONT;
    }

    public get shownFace(): RackFace | null {
        return this.viewMode === 'rear' ? this.rearFace : this.frontFace;
    }

    /** Also the value the board is zoomed by, so the read-out and the drawing cannot drift apart. */
    public get zoomLabel(): string {
        return `${this.zoomPercent}%`;
    }

    public get canZoomIn(): boolean {
        return this.zoomPercent < ZOOM_MAX;
    }

    public get canZoomOut(): boolean {
        return this.zoomPercent > ZOOM_MIN;
    }

    public get isDefaultZoom(): boolean {
        return this.zoomPercent === ZOOM_DEFAULT;
    }

    /**
     * A fullscreen element is the only thing painted, so a tooltip parked on the body would never be
     * seen. While fullscreen is open they render next to their trigger instead.
     */
    public get tooltipContainer(): string | null {
        return this.isFullscreen ? null : 'body';
    }

    public get hasLegend(): boolean {
        return this.typesLegend.length > 0 || this.occupantsLegend.length > 0;
    }

    public get visibleTypesLegend(): RackTypeLegendEntry[] {
        return this.isLegendExpanded ? this.typesLegend : this.typesLegend.slice(0, LEGEND_TYPE_LIMIT);
    }

    public get hiddenTypesCount(): number {
        return Math.max(this.typesLegend.length - LEGEND_TYPE_LIMIT, 0);
    }

    /** The legend keys the drawing, so a type entry reads its colour and icon the same way a row does. */
    public typeTone(entry: RackTypeLegendEntry): string {
        return safeAccent(entry.type_color);
    }

    public typeTint(entry: RackTypeLegendEntry): string {
        return accentTint(entry.type_color, TONE_TINT_ALPHA);
    }

    public typeIcon(entry: RackTypeLegendEntry): string {
        return safeIcon(entry.type_icon);
    }

    /** A mount is named by its object, an occupant by its own label and otherwise by its kind. */
    public labelOf(mount: RackMountRow): string {
        if (this.isMount(mount)) {
            return mount.summary_line || `#${mount.object_id}`;
        }

        return mount.label?.trim() || this.kindTitleOf(mount);
    }

    public isMount(mount: RackMountRow): boolean {
        return kindOf(mount) === RackMountKind.MOUNT;
    }

    public isSelected(mount: RackMountRow | null): boolean {
        return !!mount && this.selectedMount?.mount_id === mount.mount_id;
    }

    public kindTitleOf(mount: RackMountRow): string {
        return RACK_KIND_LABELS[kindOf(mount)];
    }

    public kindTitle(kind: RackMountKind): string {
        return RACK_KIND_LABELS[kind];
    }

    public kindIcon(kind: RackMountKind): string {
        return RACK_KIND_ICONS[kind];
    }

    /** What a row is, in one word: its type for a mount, its kind for an occupant. */
    public typeNameOf(mount: RackMountRow): string {
        return this.isMount(mount) ? mount.type_label || 'Object' : this.kindTitleOf(mount);
    }

    /** The label of a mount is already the object, so it only adds something to a named occupant. */
    public secondaryLabelOf(mount: RackMountRow): string | null {
        return this.isMount(mount) ? mount.label?.trim() || null : null;
    }

    /**
     * The booked period of a reservation, as plain days. Either end may be open, and a reservation
     * without any dates simply has no period to show.
     */
    public periodOf(mount: RackMountRow): string | null {
        const from = toDayString(mount.start_date);
        const until = toDayString(mount.end_date);

        if (from && until) {
            return `${from} to ${until}`;
        }

        if (from) {
            return `from ${from}`;
        }

        return until ? `until ${until}` : null;
    }

    public isFullDepth(mount: RackMountRow | null): boolean {
        return mount?.area === RackArea.FULL_DEPTH;
    }

    /** The U range a row covers, written the way a rack is read: the anchor first. */
    public slotRangeOf(mount: RackMountRow): string {
        if (mount.start_slot == null || mount.height == null) {
            return '';
        }

        const bottom = mount.start_slot - mount.height + 1;

        return mount.height > 1 ? `U${mount.start_slot}–U${bottom}` : `U${mount.start_slot}`;
    }

    /** Grid placement of a row: it starts at its anchor slot and spans its height. */
    public gridRowOf(mount: RackMountRow): string {
        const rackHeight = this.rack?.height ?? 0;
        const start = rackHeight - (mount.start_slot as number) + FIRST_SLOT_ROW;

        return `${start} / span ${mount.height}`;
    }

    public gridRowOfSlot(slot: number): string {
        const rackHeight = this.rack?.height ?? 0;

        return `${rackHeight - slot + FIRST_SLOT_ROW}`;
    }

    /** A rack is counted in fives, so every fifth U is drawn heavier - on the ruler and in the cavity. */
    public isMajorSlot(slot: number): boolean {
        return slot % 5 === 0 || slot === 1;
    }

    /** The row colour: its type for a mount, its own colour for a reservation, neutral otherwise. */
    public toneOf(mount: RackMountRow): string {
        return safeAccent(this.colorSourceOf(mount));
    }

    public toneTintOf(mount: RackMountRow): string {
        return accentTint(this.colorSourceOf(mount), TONE_TINT_ALPHA);
    }

    public iconOf(mount: RackMountRow): string {
        return this.isMount(mount) ? safeIcon(mount.type_icon) : RACK_KIND_ICONS[kindOf(mount)];
    }

    /* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    private setZoom(percent: number): void {
        const next = Math.min(Math.max(percent, ZOOM_MIN), ZOOM_MAX);

        if (next === this.zoomPercent) {
            return;
        }

        this.zoomPercent = next;
        this.changesRef.markForCheck();
    }

    private loadOverview(): void {
        this.loaderService.show();

        this.rackOverviewService
            .getOverview(this.publicId)
            .pipe(takeUntil(this.destroy$), finalize(() => this.loaderService.hide()))
            .subscribe({
                next: (response) => {
                    this.applyOverview(response);
                    this.changesRef.markForCheck();
                },
                error: (err) => {
                    this.hasError = true;
                    this.toastService.error(err?.error?.message);
                    this.changesRef.markForCheck();
                }
            });
    }

    private applyOverview(response: RackOverviewResponse): void {
        this.overview = response;
        this.rack = response?.rack ?? null;
        this.typesLegend = sortTypeLegend(response?.types_legend ?? []);
        this.occupantsLegend = response?.occupants_legend ?? [];
        this.hasError = false;

        this.sideRails = [
            { area: RackArea.LEFT, title: 'Left side', mounts: sortByPosition(this.mountsOf(RackArea.LEFT)) },
            { area: RackArea.RIGHT, title: 'Right side', mounts: sortByPosition(this.mountsOf(RackArea.RIGHT)) }
        ];

        this.unassignedGroup = {
            area: RackArea.UNASSIGNED,
            title: 'In the rack, not placed',
            mounts: sortByPosition(this.mountsOf(RackArea.UNASSIGNED))
        };

        this.buildElevations();
        this.restoreSelection();
    }

    /**
     * Both faces are assembled up front, so switching the view is a template change rather than a
     * rebuild. A FULL_DEPTH row holds the same slots front and back, and the backend reports it once,
     * so it is handed to both faces.
     */
    private buildElevations(): void {
        const rackHeight = this.rack?.height ?? 0;
        const fullDepth = this.mountsOf(RackArea.FULL_DEPTH);
        const front = [...this.mountsOf(RackArea.FRONT), ...fullDepth];
        const rear = [...this.mountsOf(RackArea.BACK), ...fullDepth];

        this.frontFace = buildFace(RackArea.FRONT, 'Front', front, rackHeight);
        this.rearFace = buildFace(RackArea.BACK, 'Rear', rear, rackHeight);
        this.faces = [this.frontFace, this.rearFace];
        this.bridges = fullDepth.filter(mount => fitsRack(mount, rackHeight));
        this.slotTicks = buildSlotTicks(rackHeight);

        // repeat() needs a positive count, so a rack without a height falls back to a single track.
        this.rowTemplate = rackHeight > 0
            ? `var(--rack-cap) repeat(${rackHeight}, var(--rack-u)) var(--rack-plinth)`
            : 'var(--rack-cap) minmax(6rem, auto) var(--rack-plinth)';

        this.outOfRangeMounts = collectOutOfRangeMounts([...front, ...this.mountsOf(RackArea.BACK)], rackHeight);
    }

    /** A reload replaces every row object, so the selection is matched again by its mount id. */
    private restoreSelection(): void {
        if (!this.selectedMount) {
            return;
        }

        const mountId = this.selectedMount.mount_id;
        const areas = this.overview?.areas;
        const rows = areas ? Object.values(areas).reduce<RackMountRow[]>((all, bucket) => [...all, ...bucket], []) : [];

        this.selectedMount = rows.find(row => row.mount_id === mountId) ?? null;
    }

    private mountsOf(area: RackArea): RackMountRow[] {
        return this.overview?.areas?.[area] ?? [];
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

        modalRef.componentInstance.rackId = this.publicId;
        modalRef.componentInstance.rackHeight = this.rack?.height ?? 0;
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

    /** Where the row takes its colour from: its type for a mount, its own colour for a reservation. */
    private colorSourceOf(mount: RackMountRow): string | null {
        if (this.isMount(mount)) {
            return mount.type_color;
        }

        return kindOf(mount) === RackMountKind.RESERVATION ? mount.color : null;
    }

    private deleteMount(mount: RackMountRow): void {
        this.loaderService.show();

        this.rackOverviewService
            .deleteMount(this.publicId, mount.mount_id)
            .pipe(takeUntil(this.destroy$), finalize(() => this.loaderService.hide()))
            .subscribe({
                next: () => {
                    this.selectedMount = null;
                    this.loadOverview();
                },
                error: (err) => this.toastService.error(err?.error?.message)
            });
    }
}
