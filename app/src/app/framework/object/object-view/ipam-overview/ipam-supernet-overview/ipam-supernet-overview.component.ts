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
    OnInit,
    SimpleChanges
} from '@angular/core';
import { FormControl } from '@angular/forms';
import { NgbModal } from '@ng-bootstrap/ng-bootstrap';
import { Subject, finalize, takeUntil } from 'rxjs';
import { debounceTime, distinctUntilChanged } from 'rxjs/operators';

import { CoreConfirmationModalComponent } from 'src/app/core/components/dialog/confirmation/core-confirmation-modal.component';

import { LoaderService } from 'src/app/core/services/loader.service';
import { ToastService } from 'src/app/layout/toast/toast.service';

import { Sort, SortDirection } from '../../../../../layout/table/table.types';
import {
    IpamSubnetSummary,
    IpamSupernetOverviewParams,
    IpamSupernetOverviewResponse,
    IpamSupernetSummary
} from '../models/ipam-overview.types';
import { IpamOverviewService } from '../services/ipam-overview.service';
/* ------------------------------------------------------------------------------------------------------------------ */

const DEFAULT_PAGE_SIZE = 10;
const SEARCH_DEBOUNCE_MS = 300;
const MIN_SEARCH_LENGTH = 2;

@Component({
    selector: 'cmdb-ipam-supernet-overview',
    templateUrl: './ipam-supernet-overview.component.html',
    styleUrls: ['./ipam-supernet-overview.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    standalone: false
})
export class IpamSupernetOverviewComponent implements OnInit, OnChanges, OnDestroy {

    @Input() public publicId: number | null = null;

    public supernet: IpamSupernetSummary | null = null;
    public subnetRows: IpamSubnetSummary[] = [];
    public invalidCount = 0;
    public page = 1;
    public pageSize = DEFAULT_PAGE_SIZE;
    public total = 0;
    public sort: Sort = { name: 'cidr', order: SortDirection.ASCENDING };
    public hasError = false;
    public hasLoadedOnce = false;
    public readonly searchControl = new FormControl<string>('', { nonNullable: true });
    public readonly isLoading$ = this.loaderService.isLoading$;

    private searchTerm = '';
    private readonly destroy$ = new Subject<void>();

    constructor(
        private readonly ipamOverviewService: IpamOverviewService,
        private readonly loaderService: LoaderService,
        private readonly toastService: ToastService,
        private readonly modalService: NgbModal,
        private readonly changesRef: ChangeDetectorRef
    ) {}

/* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    public ngOnInit(): void {
        this.searchControl.valueChanges
            .pipe(
                debounceTime(SEARCH_DEBOUNCE_MS),
                distinctUntilChanged(),
                takeUntil(this.destroy$)
            )
            .subscribe((value) => this.applySearch(value));
    }

    public ngOnChanges(changes: SimpleChanges): void {
        if (changes['publicId'] && this.publicId != null) {
            this.page = 1;
            this.searchTerm = '';
            this.searchControl.setValue('', { emitEvent: false });
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

    public onUnassign(subnetIds: number[]): void {
        if (this.publicId == null || !subnetIds?.length) {
            return;
        }

        const count = subnetIds.length;
        const modalRef = this.modalService.open(CoreConfirmationModalComponent, { size: 'lg' });
        modalRef.componentInstance.title = 'Unassign Subnets';
        modalRef.componentInstance.message = count === 1
            ? 'Do you want to unassign the selected subnet from this supernet?'
            : `Do you want to unassign ${count} subnets from this supernet?`;
        modalRef.componentInstance.confirmButtonText = 'Unassign';
        modalRef.componentInstance.confirmButtonClass = 'btn-danger';

        modalRef.result.then(
            (result) => {
                if (result === 'confirmed') {
                    this.unassignSubnets(subnetIds);
                }
            },
            () => {}
        );
    }

/* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    public hasOverviewData(): boolean {
        return !this.hasError && this.supernet !== null;
    }

    public get isSearching(): boolean {
        return this.searchTerm.length >= MIN_SEARCH_LENGTH;
    }

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    private unassignSubnets(subnetIds: number[]): void {
        if (this.publicId == null) {
            return;
        }

        this.loaderService.show();

        this.ipamOverviewService
            .unassignSubnetsFromSupernet(this.publicId, subnetIds)
            .pipe(
                takeUntil(this.destroy$),
                finalize(() => this.loaderService.hide())
            )
            .subscribe({
                next: (response) => {
                    const count = response?.unassigned_count ?? subnetIds.length;
                    this.toastService.success(
                        count === 1
                            ? 'Subnet unassigned successfully.'
                            : `${count} subnets unassigned successfully.`
                    );
                    this.loadOverview();
                },
                error: (err) => {
                    this.toastService.error(err?.error?.message);
                }
            });
    }

    private applySearch(value: string): void {
        const trimmed = (value ?? '').trim();

        if (trimmed.length > 0 && trimmed.length < MIN_SEARCH_LENGTH) {
            return;
        }

        if (trimmed === this.searchTerm) {
            return;
        }

        this.searchTerm = trimmed;
        this.page = 1;
        this.loadOverview();
    }

    private loadOverview(): void {
        if (this.publicId == null) {
            return;
        }

        this.hasError = false;
        this.loaderService.show();

        const params: IpamSupernetOverviewParams = {
            page: this.page,
            page_size: this.pageSize,
            sort: this.sort?.name,
            order: this.sort?.order,
            search: this.searchTerm || undefined
        };

        this.ipamOverviewService
            .getSupernetOverview(this.publicId, params)
            .pipe(
                takeUntil(this.destroy$),
                finalize(() => this.loaderService.hide())
            )
            .subscribe({
                next: (response: IpamSupernetOverviewResponse) => {
                    const subnetsPage = response?.subnets;
                    this.supernet = response?.supernet ?? null;
                    this.subnetRows = subnetsPage?.rows ?? [];
                    this.invalidCount = response?.invalid_count ?? 0;
                    this.page = subnetsPage?.page ?? this.page;
                    this.pageSize = subnetsPage?.page_size ?? this.pageSize;
                    this.total = subnetsPage?.total ?? 0;
                    this.hasLoadedOnce = true;
                    this.changesRef.markForCheck();
                },
                error: (err) => {
                    this.hasError = true;
                    this.supernet = null;
                    this.subnetRows = [];
                    this.invalidCount = 0;
                    this.total = 0;
                    this.hasLoadedOnce = true;
                    this.toastService.error(err?.error?.message);
                    this.changesRef.markForCheck();
                }
            });
    }
}
