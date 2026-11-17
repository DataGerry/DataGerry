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
    Component,
    computed,
    DestroyRef,
    effect,
    inject,
    input,
    signal,
    untracked
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { finalize, Subscription } from 'rxjs';

import { CmdbLog } from '../../../../models/cmdb-log';
import { LogMode } from '../../../../modes.enum';
import { LogService } from 'src/app/framework/services/log.service';
import { LoaderService } from 'src/app/core/services/loader.service';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { DateSettingsService } from 'src/app/settings/services/date-settings.service';
import { APIGetMultiResponse } from 'src/app/services/models/api-response';
import { CollectionParameters } from 'src/app/services/models/api-parameter';
import { SortDirection } from 'src/app/layout/table/table.types';
import { TimelineDay } from './object-log-timeline.types';
import { buildTimeline } from './object-log-timeline.utils';
/* ------------------------------------------------------------------------------------------------------------------ */

const PAGE_SIZE = 25;

@Component({
    selector: 'cmdb-object-log-timeline',
    templateUrl: './object-log-timeline.component.html',
    styleUrls: ['./object-log-timeline.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    standalone: false
})
export class ObjectLogTimelineComponent {

    public readonly publicID = input.required<number>();

    public readonly MODES = LogMode;

    private readonly logs = signal<CmdbLog[]>([]);
    private readonly total = signal(0);
    private readonly page = signal(1);
    private readonly expandedGroups = signal<ReadonlySet<string>>(new Set());

    public readonly loaded = signal(false);

    public readonly days = computed<TimelineDay[]>(() =>
        buildTimeline(this.logs(), this.dateSettingsService.currentDateSettings?.timezone, new Date())
    );

    public readonly hasMore = computed(() => this.logs().length < this.total());

    private readonly logService = inject(LogService);
    private readonly loaderService = inject(LoaderService);
    private readonly toast = inject(ToastService);
    private readonly dateSettingsService = inject(DateSettingsService);
    private readonly destroyRef = inject(DestroyRef);

    private logRequest?: Subscription;

/* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    constructor() {
        effect(() => {
            const objectID = this.publicID();
            untracked(() => this.reload(objectID));
        });
    }

/* ---------------------------------------------------- EVENTS ------------------------------------------------------ */

    public onLoadMore(): void {
        this.loadPage(this.publicID(), this.page() + 1);
    }

    public onToggleGroup(groupID: string): void {
        this.expandedGroups.update(groups => {
            const next = new Set(groups);

            if (!next.delete(groupID)) {
                next.add(groupID);
            }

            return next;
        });
    }

/* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    public isExpanded(groupID: string): boolean {
        return this.expandedGroups().has(groupID);
    }

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    private reload(objectID: number): void {
        this.logs.set([]);
        this.total.set(0);
        this.expandedGroups.set(new Set());
        this.loaded.set(false);
        this.loadPage(objectID, 1);
    }

    private loadPage(objectID: number, page: number): void {
        if (objectID === undefined || objectID === null) {
            return;
        }

        const params: CollectionParameters = {
            filter: [{ $match: { log_type: 'CmdbObjectLog', object_id: objectID } }],
            limit: PAGE_SIZE,
            sort: 'log_time',
            order: SortDirection.DESCENDING,
            page,
        };

        this.logRequest?.unsubscribe();
        this.loaderService.show();
        this.logRequest = this.logService.getLogsByObject(objectID, params)
            .pipe(takeUntilDestroyed(this.destroyRef), finalize(() => this.loaderService.hide()))
            .subscribe({
                next: (response: APIGetMultiResponse<CmdbLog>) => {
                    this.logs.update(current => page === 1 ? response.results : [...current, ...response.results]);
                    this.total.set(response.total);
                    this.page.set(page);
                    this.loaded.set(true);
                },
                error: () => {
                    this.loaded.set(true);
                    this.toast.error('The object logs could not be loaded.');
                }
            });
    }
}
