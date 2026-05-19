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
    Input,
    OnChanges,
    OnDestroy,
    SimpleChanges
} from '@angular/core';
import { Subject, finalize, takeUntil } from 'rxjs';

import { LoaderService } from 'src/app/core/services/loader.service';
import { ToastService } from 'src/app/layout/toast/toast.service';

import { Sort, SortDirection } from '../../../../../layout/table/table.types';
import {
    IpamIpEntry,
    IpamIpDistribution,
    IpamSubnetDetail,
    IpamSubnetOverviewParams,
    IpamSubnetOverviewResponse,
    IpamTypeDistributionEntry
} from '../models/ipam-overview.types';
import { IpamOverviewService } from '../services/ipam-overview.service';
/* ------------------------------------------------------------------------------------------------------------------ */

const DEFAULT_PAGE_SIZE = 10;

@Component({
    selector: 'cmdb-ipam-subnet-overview',
    templateUrl: './ipam-subnet-overview.component.html',
    styleUrls: ['./ipam-subnet-overview.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    standalone: false
})
export class IpamSubnetOverviewComponent implements OnChanges, OnDestroy {

    @Input() public publicId: number | null = null;

    public ips: IpamIpEntry[] = [];
    public subnet: IpamSubnetDetail | null = null;
    public ipDistribution: IpamIpDistribution | null = null;
    public typeDistribution: IpamTypeDistributionEntry[] = [];
    public page = 1;
    public pageSize = DEFAULT_PAGE_SIZE;
    public total = 0;
    public sort: Sort = { name: 'ip', order: SortDirection.ASCENDING };
    public hasError = false;
    public hasLoadedOnce = false;
    public readonly isLoading$ = this.loaderService.isLoading$;

    private readonly destroy$ = new Subject<void>();

    constructor(
        private readonly ipamOverviewService: IpamOverviewService,
        private readonly loaderService: LoaderService,
        private readonly toastService: ToastService,
        private readonly changesRef: ChangeDetectorRef
    ) {}

/* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    public ngOnChanges(changes: SimpleChanges): void {
        if (changes['publicId'] && this.publicId != null) {
            this.page = 1;
            this.loadOverview();
        }
    }

    public ngOnDestroy(): void {
        this.destroy$.next();
        this.destroy$.complete();
    }

/* ---------------------------------------------------- EVENTS ------------------------------------------------------ */

    public onPageChange(page: number): void {
        if (page === this.page) {
            return;
        }
        this.page = page;
        this.loadOverview();
    }

    public onPageSizeChange(size: number): void {
        this.pageSize = size;
        this.page = 1;
        this.loadOverview();
    }

    public onSortChange(sort: Sort): void {
        this.sort = sort;
        this.page = 1;
        this.loadOverview();
    }

/* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    public get isReady(): boolean {
        return this.hasLoadedOnce && !this.hasError;
    }

    public get hasRows(): boolean {
        return this.isReady && this.ips.length > 0;
    }

    public get hasSubnetDetail(): boolean {
        return this.subnet !== null;
    }

    public get usedPercent(): number | null {
        return this.computeShare(this.subnet?.used_ips);
    }

    public get freePercent(): number | null {
        return this.computeShare(this.subnet?.free_ips);
    }

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    private computeShare(part: number | null | undefined): number | null {
        if (part == null) {
            return null;
        }
        const denominator = this.subnet?.assignable_ips ?? this.subnet?.total_ips;
        if (!denominator || denominator <= 0) {
            return null;
        }
        return (part / denominator) * 100;
    }

    private loadOverview(): void {
        if (this.publicId == null) {
            return;
        }

        this.hasError = false;
        this.loaderService.show();

        const params: IpamSubnetOverviewParams = {
            page: this.page,
            page_size: this.pageSize,
            sort: this.sort?.name,
            order: this.sort?.order
        };

        this.ipamOverviewService
            .getSubnetOverview(this.publicId, params)
            .pipe(
                takeUntil(this.destroy$),
                finalize(() => this.loaderService.hide())
            )
            .subscribe({
                next: (response: IpamSubnetOverviewResponse) => {
                    const ipsPage = response?.ips;
                    this.ips = ipsPage?.rows ?? [];
                    this.subnet = response?.subnet ?? null;
                    this.ipDistribution = response?.ip_distribution ?? null;
                    this.typeDistribution = response?.type_distribution ?? [];
                    this.page = ipsPage?.page ?? this.page;
                    this.pageSize = ipsPage?.page_size ?? this.pageSize;
                    this.total = ipsPage?.total ?? 0;
                    this.hasLoadedOnce = true;
                    this.changesRef.markForCheck();
                },
                error: (err) => {
                    this.hasError = true;
                    this.ips = [];
                    this.subnet = null;
                    this.ipDistribution = null;
                    this.typeDistribution = [];
                    this.total = 0;
                    this.hasLoadedOnce = true;
                    this.toastService.error(err?.error?.message);
                    this.changesRef.markForCheck();
                }
            });
    }
}
