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

import { IpamSupernetSummary } from './models/ipam-overview.types';
import { IpamOverviewService } from './services/ipam-overview.service';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'cmdb-ipam-overview',
    templateUrl: './ipam-overview.component.html',
    styleUrls: ['./ipam-overview.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    standalone: false
})
export class IpamOverviewComponent implements OnChanges, OnDestroy {

    @Input() public publicId: number | null = null;

    public supernet: IpamSupernetSummary | null = null;
    public hasError = false;
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
            this.loadOverview(this.publicId);
        }
    }

    public ngOnDestroy(): void {
        this.destroy$.next();
        this.destroy$.complete();
    }

/* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    public hasOverviewData(): boolean {
        return !this.hasError && this.supernet !== null;
    }

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    private loadOverview(publicId: number): void {
        this.hasError = false;
        this.loaderService.show();

        this.ipamOverviewService
            .getSupernetOverview(publicId)
            .pipe(
                takeUntil(this.destroy$),
                finalize(() => this.loaderService.hide())
            )
            .subscribe({
                next: (response) => {
                    this.supernet = response?.supernet ?? null;
                    this.changesRef.markForCheck();
                },
                error: (err) => {
                    this.hasError = true;
                    this.supernet = null;
                    this.toastService.error(err?.error?.message);
                    this.changesRef.markForCheck();
                }
            });
    }
}
