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
import { LoaderService } from 'src/app/core/services/loader.service';
import { ToastService } from 'src/app/layout/toast/toast.service';

import { RackMountModalComponent } from './components/rack-mount-modal/rack-mount-modal.component';
import {
    RackArea,
    RackAreaGroup,
    RackHeader,
    RackMountKind,
    RackMountRow,
    RackOccupantLegendEntry,
    RackOverviewResponse,
    RackSlotRow,
    RackViewSide,
    kindOf,
    toDayString
} from './models/rack-overview.types';
import { RackOverviewService } from './services/rack-overview.service';
import { buildSlotRows, collectOutOfRangeMounts, sortByPosition } from './utils/rack-layout.util';
import { RACK_KIND_ICONS, RACK_KIND_LABELS, accentTint, safeAccent, safeIcon } from './utils/rack-visual.util';
/* ------------------------------------------------------------------------------------------------------------------ */

/** Opacity of the type colour filling the row of a mounted object. */
const ROW_TINT_ALPHA = 0.22;


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
    private readonly modalService = inject(NgbModal);
    private readonly router = inject(Router);
    private readonly changesRef = inject(ChangeDetectorRef);

    @Input() public publicId: number | null = null;

    public readonly AREAS = RackArea;
    public readonly isLoading$ = this.loaderService.isLoading$;

    public rack: RackHeader | null = null;
    public totalMounts = 0;
    public activeSide: RackViewSide = RackArea.FRONT;
    public slotRows: RackSlotRow[] = [];
    public outOfRangeMounts: RackMountRow[] = [];
    public positionAreaGroups: RackAreaGroup[] = [];
    public occupantsLegend: RackOccupantLegendEntry[] = [];
    public hasError = false;

    private overview: RackOverviewResponse | null = null;
    private readonly destroy$ = new Subject<void>();

/* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    public ngOnChanges(changes: SimpleChanges): void {
        if (changes['publicId'] && this.publicId != null) {
            this.activeSide = RackArea.FRONT;
            this.loadOverview();
        }
    }

    public ngOnDestroy(): void {
        this.destroy$.next();
        this.destroy$.complete();
    }

/* ---------------------------------------------------- EVENTS ------------------------------------------------------ */

    public onSideChange(side: RackViewSide): void {
        if (side === this.activeSide) {
            return;
        }

        this.activeSide = side;
        this.buildActiveSide();
        this.changesRef.markForCheck();
    }

    public onMountObject(): void {
        this.openMountModal(null, this.activeSide, null);
    }

    /** Filling the clicked slot, pre-filled with that slot as the anchor. */
    public onFreeSlotClick(row: RackSlotRow): void {
        if (row.mount) {
            return;
        }

        this.openMountModal(null, this.activeSide, row.slot);
    }

    public onEditMount(mount: RackMountRow): void {
        this.openMountModal(mount, mount.area, mount.start_slot);
    }

    /** Frees the slots but keeps the object in the rack, so it can be placed again later. */
    public onUnplaceMount(mount: RackMountRow): void {
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

    public kindTitleOf(mount: RackMountRow): string {
        return RACK_KIND_LABELS[kindOf(mount)];
    }

    public kindTitle(kind: RackMountKind): string {
        return RACK_KIND_LABELS[kind];
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

    /** A row is exactly as tall as the U it covers, which is what makes the grid read as a rack. */
    public heightOf(row: RackSlotRow): string {
        return `calc(var(--rack-u) * ${row.span})`;
    }

    /**
     * The U numbers this row covers, top down. The rulers are drawn from the rows themselves rather
     * than from a separate list of slots, so the two can never drift apart.
     */
    public ticksOf(row: RackSlotRow): number[] {
        return Array.from({ length: row.span }, (_, index) => row.slot - index);
    }

    public accentOf(mount: RackMountRow): string {
        return safeAccent(this.colorSourceOf(mount));
    }

    public accentTintOf(mount: RackMountRow): string {
        return accentTint(this.colorSourceOf(mount), ROW_TINT_ALPHA);
    }

    public kindIcon(kind: RackMountKind): string {
        return RACK_KIND_ICONS[kind];
    }

    public iconOf(mount: RackMountRow): string {
        return this.isMount(mount) ? safeIcon(mount.type_icon) : RACK_KIND_ICONS[kindOf(mount)];
    }

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

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
        this.totalMounts = response?.total_mounts ?? 0;
        this.occupantsLegend = response?.occupants_legend ?? [];
        this.hasError = false;

        this.positionAreaGroups = [
            { area: RackArea.LEFT, title: 'Left side', mounts: sortByPosition(this.mountsOf(RackArea.LEFT)) },
            { area: RackArea.RIGHT, title: 'Right side', mounts: sortByPosition(this.mountsOf(RackArea.RIGHT)) },
            {
                area: RackArea.UNASSIGNED,
                title: 'Assigned, not placed',
                mounts: sortByPosition(this.mountsOf(RackArea.UNASSIGNED))
            }
        ];

        this.buildActiveSide();
    }

    /**
     * A side shows its own mounts plus every FULL_DEPTH one: those occupy the same slots in the front
     * and the rear, and the backend reports them once instead of duplicating them into both buckets.
     */
    private buildActiveSide(): void {
        const rackHeight = this.rack?.height ?? 0;
        const mounts = [...this.mountsOf(this.activeSide), ...this.mountsOf(RackArea.FULL_DEPTH)];

        this.slotRows = buildSlotRows(mounts, rackHeight);
        this.outOfRangeMounts = collectOutOfRangeMounts(mounts, rackHeight);
    }

    private mountsOf(area: RackArea): RackMountRow[] {
        return this.overview?.areas?.[area] ?? [];
    }

    private openMountModal(mount: RackMountRow | null, presetArea: RackArea, presetStartSlot: number | null): void {
        const modalRef = this.modalService.open(RackMountModalComponent, {
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
                next: () => this.loadOverview(),
                error: (err) => this.toastService.error(err?.error?.message)
            });
    }
}
