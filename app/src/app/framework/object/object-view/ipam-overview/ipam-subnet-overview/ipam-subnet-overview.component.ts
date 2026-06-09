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
    Component,
    inject,
    ChangeDetectionStrategy,
    ChangeDetectorRef,
    Input,
    OnChanges,
    OnDestroy,
    SimpleChanges,
} from '@angular/core';
import { HttpErrorResponse, HttpResponse } from '@angular/common/http';
import { NgbModal } from '@ng-bootstrap/ng-bootstrap';
import { FileSaverService } from 'ngx-filesaver';
import { Observable, Subject, catchError, finalize, of, switchMap, takeUntil, tap } from 'rxjs';

import { LoaderService } from 'src/app/core/services/loader.service';
import { ToastService } from 'src/app/layout/toast/toast.service';

import { Sort, SortDirection } from '../../../../../layout/table/table.types';
import {
    IpamIpEntry,
    IpamIpDistribution,
    IpamSectorRange,
    IpamSubnetDetail,
    IpamSubnetOverviewParams,
    IpamSubnetOverviewResponse,
    IpamSubnetSectorParams,
    IpamSubnetSectorResponse,
    IpamTypeDistributionEntry,
    IpamUnassignMode,
    IpamVlanInfo
} from '../models/ipam-overview.types';
import { IpamOverviewService } from '../services/ipam-overview.service';
import { IpamUnassignIpModalComponent } from '../components/ipam-unassign-ip-modal/ipam-unassign-ip-modal.component';
/* ------------------------------------------------------------------------------------------------------------------ */

const DEFAULT_PAGE_SIZE = 10;
const VLAN_CARD_VISIBLE_LIMIT = 2;

type IpamIpsRequestKind = 'overview' | 'sector';

interface IpamIpsRequest {
    publicId: number;
    kind: IpamIpsRequestKind;
    page: number;
    pageSize: number;
    sort: Sort;
    sectorStart: string | null;
}

@Component({
    selector: 'cmdb-ipam-subnet-overview',
    templateUrl: './ipam-subnet-overview.component.html',
    styleUrls: ['./ipam-subnet-overview.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    standalone: false
})
export class IpamSubnetOverviewComponent implements OnChanges, OnDestroy {
    private readonly ipamOverviewService = inject(IpamOverviewService);
    private readonly loaderService = inject(LoaderService);
    private readonly toastService = inject(ToastService);
    private readonly modalService = inject(NgbModal);
    private readonly fileSaverService = inject(FileSaverService);
    private readonly changesRef = inject(ChangeDetectorRef);

    @Input() public publicId: number | null = null;

    public ips: IpamIpEntry[] = [];
    public subnet: IpamSubnetDetail | null = null;
    public ipDistribution: IpamIpDistribution | null = null;
    public typeDistribution: IpamTypeDistributionEntry[] = [];
    public vlans: IpamVlanInfo[] = [];
    public page = 1;
    public pageSize = DEFAULT_PAGE_SIZE;
    public total = 0;
    public sort: Sort = { name: 'ip', order: SortDirection.ASCENDING };
    public hasError = false;
    public hasLoadedOnce = false;
    public isFullscreen = false;
    public selectedSectorStart: string | null = null;
    public selectedSectorRange: IpamSectorRange | null = null;
    public readonly isLoading$ = this.loaderService.isLoading$;

    private readonly destroy$ = new Subject<void>();
    private readonly ipsRequest$ = new Subject<IpamIpsRequest>();

/* --------------------------------------------------- CONSTRUCTOR -------------------------------------------------- */

    constructor() {
        this.ipsRequest$
            .pipe(
                switchMap(request => this.executeIpsRequest(request)),
                takeUntil(this.destroy$)
            )
            .subscribe();
    }

/* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    public ngOnChanges(changes: SimpleChanges): void {
        if (changes['publicId'] && this.publicId != null) {
            this.page = 1;
            this.clearSectorSelection();
            this.dispatchIpsRequest();
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
        this.dispatchIpsRequest();
    }

    public onPageSizeChange(size: number): void {
        this.pageSize = size;
        this.page = 1;
        this.dispatchIpsRequest();
    }

    public onSortChange(sort: Sort): void {
        this.sort = sort;
        this.page = 1;
        this.clearSectorSelection();
        this.dispatchIpsRequest();
    }

    public onFullscreenChange(isFullscreen: boolean): void {
        this.isFullscreen = isFullscreen;
        this.changesRef.markForCheck();
    }

    public onSectorSelect(sectorStart: string): void {
        this.selectedSectorStart = sectorStart;
        this.page = 1;
        this.dispatchIpsRequest();
    }

    public onClearSector(): void {
        this.clearSectorSelection();
        this.page = 1;
        this.dispatchIpsRequest();
    }

    public onShowAllIps(): void {
        if (this.hasSelectedSector) {
            this.onClearSector();
        }
    }

    public onUnassign(ips: string[]): void {
        if (this.publicId == null || !ips?.length) {
            return;
        }

        const modalRef = this.modalService.open(IpamUnassignIpModalComponent, { size: 'lg' });
        modalRef.componentInstance.count = ips.length;
        modalRef.componentInstance.ipLabel = ips.length === 1 ? ips[0] : null;

        modalRef.result.then(
            (mode: IpamUnassignMode) => this.unassignIps(ips, mode),
            () => {}
        );
    }

    public onExport(): void {
        if (this.publicId == null) {
            return;
        }

        this.loaderService.show();

        this.ipamOverviewService
            .exportSubnetOverview(this.publicId)
            .pipe(
                takeUntil(this.destroy$),
                finalize(() => this.loaderService.hide())
            )
            .subscribe({
                next: (response) => this.saveExportFile(response),
                error: () => this.toastService.error('Unable to export the subnet overview. Please try again later.')
            });
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

    public get hasSelectedSector(): boolean {
        return this.selectedSectorStart !== null;
    }

    public get selectedSectorLabel(): string {
        if (!this.selectedSectorRange) {
            return '';
        }
        return `${this.selectedSectorRange.ip_start} - ${this.selectedSectorRange.ip_end}`;
    }

    public get usedPercent(): number | null {
        return this.computeShare(this.subnet?.used_ips);
    }

    public get freePercent(): number | null {
        return this.computeShare(this.subnet?.free_ips);
    }

    public get namedVlans(): IpamVlanInfo[] {
        return this.vlans?.filter(vlan => !!vlan?.name) ?? [];
    }

    public get hasVlans(): boolean {
        return this.namedVlans.length > 0;
    }

    public get visibleVlans(): IpamVlanInfo[] {
        return this.namedVlans.slice(0, VLAN_CARD_VISIBLE_LIMIT);
    }

    public get hiddenVlanCount(): number {
        return Math.max(0, this.namedVlans.length - VLAN_CARD_VISIBLE_LIMIT);
    }

    public get vlanTooltip(): string {
        return this.namedVlans.map(vlan => this.vlanLabel(vlan)).join(', ');
    }

    public vlanLabel(vlan: IpamVlanInfo): string {
        return vlan?.name?.trim() || `VLAN ${vlan?.public_id ?? ''}`.trim();
    }

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    private unassignIps(ips: string[], mode: IpamUnassignMode): void {
        if (this.publicId == null || !ips?.length) {
            return;
        }

        this.loaderService.show();

        this.ipamOverviewService
            .unassignIpsFromSubnet(this.publicId, ips, mode)
            .pipe(
                takeUntil(this.destroy$),
                finalize(() => this.loaderService.hide())
            )
            .subscribe({
                next: (response) => {
                    const count = response?.unassigned_count ?? ips.length;
                    this.toastService.success(
                        count === 1
                            ? 'IP address unassigned successfully.'
                            : `${count} IP addresses unassigned successfully.`
                    );
                    this.dispatchIpsRequest();
                },
                error: (err) => {
                    this.toastService.error(err?.error?.message);
                }
            });
    }

    private saveExportFile(response: HttpResponse<Blob>): void {
        const blob = response?.body;
        if (!blob) {
            this.toastService.error('The export response was empty.');
            return;
        }
        this.fileSaverService.save(blob, this.buildExportFileName());
    }

    private buildExportFileName(): string {
        const cidr = this.subnet?.cidr?.replace(/[^\w.-]+/g, '_');
        return `subnet-overview-${cidr || this.publicId}.xlsx`;
    }

    private clearSectorSelection(): void {
        this.selectedSectorStart = null;
        this.selectedSectorRange = null;
    }

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

    private dispatchIpsRequest(): void {
        if (this.publicId == null) {
            return;
        }

        this.loaderService.show();
        this.ipsRequest$.next({
            publicId: this.publicId,
            kind: this.selectedSectorStart ? 'sector' : 'overview',
            page: this.page,
            pageSize: this.pageSize,
            sort: this.sort,
            sectorStart: this.selectedSectorStart
        });
    }

    private executeIpsRequest(request: IpamIpsRequest): Observable<unknown> {
        if (request.kind === 'sector' && request.sectorStart) {
            return this.requestSectorIps(request, request.sectorStart);
        }
        return this.requestOverview(request);
    }

    private requestOverview(request: IpamIpsRequest): Observable<unknown> {
        this.hasError = false;

        const params: IpamSubnetOverviewParams = {
            page: request.page,
            page_size: request.pageSize,
            sort: request.sort?.name,
            order: request.sort?.order
        };

        return this.ipamOverviewService.getSubnetOverview(request.publicId, params).pipe(
            tap((response: IpamSubnetOverviewResponse) => this.applyOverviewResponse(response)),
            catchError((err) => {
                this.handleOverviewError(err);
                return of(null);
            }),
            finalize(() => this.loaderService.hide())
        );
    }

    private requestSectorIps(request: IpamIpsRequest, sectorStart: string): Observable<unknown> {
        const params: IpamSubnetSectorParams = {
            page: request.page,
            page_size: request.pageSize
        };

        return this.ipamOverviewService.getSubnetSectorIps(request.publicId, sectorStart, params).pipe(
            tap((response: IpamSubnetSectorResponse) => this.applySectorResponse(response)),
            catchError((err) => {
                this.handleSectorError(err);
                return of(null);
            }),
            finalize(() => this.loaderService.hide())
        );
    }

    private applyOverviewResponse(response: IpamSubnetOverviewResponse): void {
        const ipsPage = response?.ips;
        this.ips = ipsPage?.rows ?? [];
        this.subnet = response?.subnet ?? null;
        this.ipDistribution = response?.ip_distribution ?? null;
        this.typeDistribution = response?.type_distribution ?? [];
        this.vlans = response?.vlans ?? [];
        this.page = ipsPage?.page ?? this.page;
        this.pageSize = ipsPage?.page_size ?? this.pageSize;
        this.total = ipsPage?.total ?? 0;
        this.hasLoadedOnce = true;
        this.changesRef.markForCheck();
    }

    private handleOverviewError(err: HttpErrorResponse): void {
        this.hasError = true;
        this.ips = [];
        this.subnet = null;
        this.ipDistribution = null;
        this.typeDistribution = [];
        this.vlans = [];
        this.total = 0;
        this.hasLoadedOnce = true;
        this.toastService.error(err?.error?.message);
        this.changesRef.markForCheck();
    }

    private applySectorResponse(response: IpamSubnetSectorResponse): void {
        const ipsPage = response?.ips;
        this.ips = ipsPage?.rows ?? [];
        this.selectedSectorRange = response?.sector ?? null;
        this.page = ipsPage?.page ?? this.page;
        this.pageSize = ipsPage?.page_size ?? this.pageSize;
        this.total = ipsPage?.total ?? 0;
        this.changesRef.markForCheck();
    }

    private handleSectorError(err: HttpErrorResponse): void {
        this.ips = [];
        this.total = 0;
        this.toastService.error(err?.error?.message);
        this.changesRef.markForCheck();
    }
}
