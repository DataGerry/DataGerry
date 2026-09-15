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
import { Subject, of, switchMap, takeUntil } from 'rxjs';

import { RenderResult } from 'src/app/framework/models/cmdb-render';
import { ObjectService } from 'src/app/framework/services/object.service';

import { RackArea, RackMount } from '../../models/rack-overview.types';
import { RackOverviewService } from '../../services/rack-overview.service';
/* ------------------------------------------------------------------------------------------------------------------ */


/**
 * Tells a mounted object's own page which rack it sits in. The mount lives in its own collection, so
 * the object itself carries no hint of it - it has to be looked up by object id.
 */
@Component({
    selector: 'cmdb-rack-placement',
    templateUrl: './rack-placement.component.html',
    styleUrls: ['./rack-placement.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    standalone: false
})
export class RackPlacementComponent implements OnChanges, OnDestroy {

    private readonly rackOverviewService = inject(RackOverviewService);
    private readonly objectService = inject(ObjectService);
    private readonly router = inject(Router);
    private readonly changesRef = inject(ChangeDetectorRef);

    @Input() public objectId: number | null = null;

    public mount: RackMount | null = null;
    public rackLabel = '';

    private readonly destroy$ = new Subject<void>();

/* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    public ngOnChanges(changes: SimpleChanges): void {
        if (changes['objectId'] && this.objectId != null) {
            this.loadPlacement();
        }
    }

    public ngOnDestroy(): void {
        this.destroy$.next();
        this.destroy$.complete();
    }

/* ---------------------------------------------------- EVENTS ------------------------------------------------------ */

    public onOpenRack(): void {
        if (!this.mount) {
            return;
        }

        this.router.navigate([`/framework/object/view/${this.mount.rack_id}`]);
    }

/* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    /** Where inside the rack the object sits, or that it is a member without a place yet. */
    public get placementText(): string {
        if (!this.mount) {
            return '';
        }

        if (this.mount.area === RackArea.UNASSIGNED) {
            return 'assigned to the rack, not placed yet';
        }

        if (this.mount.start_slot == null || this.mount.height == null) {
            return `${this.mount.area.toLowerCase()} area`;
        }

        const bottom = this.mount.start_slot - this.mount.height + 1;
        const slots = this.mount.height > 1 ? `slots ${this.mount.start_slot} to ${bottom}` : `slot ${bottom}`;

        return `${this.mount.area.replace('_', ' ').toLowerCase()}, ${slots}`;
    }

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    /**
     * Runs quietly: an object that is not mounted answers 200 with a null body, and a failed lookup
     * only means this hint is missing, so neither case is worth a notification.
     */
    private loadPlacement(): void {
        this.rackOverviewService
            .getMountOfObject(this.objectId)
            .pipe(
                switchMap((mount) => {
                    this.mount = mount;
                    return mount ? this.objectService.getObject<RenderResult>(mount.rack_id) : of(null);
                }),
                takeUntil(this.destroy$)
            )
            .subscribe({
                next: (rack) => {
                    this.rackLabel = this.buildRackLabel(rack);
                    this.changesRef.markForCheck();
                },
                error: () => {
                    this.mount = null;
                    this.changesRef.markForCheck();
                }
            });
    }

    private buildRackLabel(rack: RenderResult | null): string {
        if (!this.mount) {
            return '';
        }

        return rack?.summary_line || `#${this.mount.rack_id}`;
    }
}
