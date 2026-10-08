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
import { Component, inject, Input, OnChanges, OnDestroy, SimpleChanges } from '@angular/core';
import { forkJoin, of } from 'rxjs';
import { catchError, finalize } from 'rxjs/operators';

import { AutomationsService } from '../../services/automations.service';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { AutomationRunEntry } from '../../models/automation-run-log.model';
/* ------------------------------------------------------------------------------------------------------------------ */

/** How often the panel asks whether the run it started has finished. */
const POLL_INTERVAL_MS = 3000;

/** When to stop asking. A run that outlives this is still running - the list just stops chasing it. */
const POLL_LIMIT_MS = 10 * 60 * 1000;


/**
 * Starting an automation and reading what the run did, in one place.
 *
 * Sits in the wizard's last step so the loop that matters - change something, run it, see what
 * happened - closes without leaving the editor. The list offers both the runs that succeeded and
 * the ones that failed, because the failed ones are the reason anybody opens this.
 *
 * A run can only be started once the automation exists: the scheduler is what is executed, and an
 * automation that has not been saved has none. The panel says so rather than offering a button that
 * cannot work.
 *
 * The panel owns its own service calls, which keeps the step component the dumb input/output shell
 * the other steps are.
 */
@Component({
    selector: 'app-automation-run-panel',
    templateUrl: './automation-run-panel.component.html',
    styleUrls: ['./automation-run-panel.component.scss'],
    standalone: false
})
export class AutomationRunPanelComponent implements OnChanges, OnDestroy {

    @Input() public schedulerId: number | null = null;
    @Input() public connectionId: number | null = null;

    /**
     * An advisory shown beside the buttons - not a block.
     *
     * A saved automation can always be run; what a caller may need to add is what the run will
     * actually execute, which is the last saved version rather than whatever is on screen.
     */
    @Input() public note = '';

    public runs: AutomationRunEntry[] = [];
    public selected: AutomationRunEntry | null = null;
    public loadingRuns = false;
    public starting = false;
    public running = false;
    public listError = '';

    private pollTimerId?: number;
    private pollStartedAt = 0;

    private readonly automationsService = inject(AutomationsService);
    private readonly toast = inject(ToastService);

    /* -------------------------------------------------- LIFE CYCLE -------------------------------------------------- */

    public ngOnChanges(changes: SimpleChanges): void {
        if (changes['schedulerId']) {
            this.selected = null;
            this.runs = [];
            this.loadRuns();
        }
    }


    public ngOnDestroy(): void {
        this.stopPolling();
    }

    /* --------------------------------------------------- ACTIONS ---------------------------------------------------- */

    /**
     * Fetches the runs of this automation, successful and failed together.
     *
     * The two are separate endpoints and neither knows about the other, so they are merged here and
     * sorted newest first - which is the order anybody looking for "what just happened" wants.
     */
    public loadRuns(onLoaded?: () => void): void {
        const schedulerId = this.schedulerId;

        if (!schedulerId) {
            return;
        }

        this.loadingRuns = true;
        this.listError = '';

        forkJoin([
            this.automationsService.getSchedulerLogs(schedulerId, 's').pipe(catchError(() => of([]))),
            this.automationsService.getSchedulerLogs(schedulerId, 'f').pipe(catchError(() => of([])))
        ])
            .pipe(finalize(() => {
                this.loadingRuns = false;
            }))
            .subscribe({
                next: ([succeeded, failed]) => {
                    this.runs = [
                        ...this.tag(succeeded, 's'),
                        ...this.tag(failed, 'f')
                    ].sort((left, right) => this.dateOf(right) - this.dateOf(left));
                    onLoaded?.();
                },
                error: err => {
                    this.listError = err?.error?.message || 'The runs of this automation could not be loaded.';
                }
            });
    }


    /**
     * Starts the automation and waits for it to finish before refreshing the list.
     *
     * OpenCelium answers the start immediately and writes the log as it goes, so the new run is
     * only in the list once the scheduler has stopped running - which is what the polling is for.
     */
    public start(): void {
        const schedulerId = this.schedulerId;

        if (!schedulerId || this.starting || this.running) {
            return;
        }

        this.starting = true;

        this.automationsService.executeScheduler(schedulerId)
            .pipe(finalize(() => {
                this.starting = false;
            }))
            .subscribe({
                next: () => {
                    this.toast.success('The automation was started.');
                    this.running = true;
                    this.beginPolling();
                },
                error: err => {
                    this.toast.error(err?.error?.message || 'The automation could not be started.');
                }
            });
    }


    public select(entry: AutomationRunEntry): void {
        this.selected = this.selected?.execution_id === entry.execution_id ? null : entry;
    }


    public isSelected(entry: AutomationRunEntry): boolean {
        return this.selected?.execution_id === entry.execution_id;
    }

    /* --------------------------------------------------- POLLING ---------------------------------------------------- */

    private beginPolling(): void {
        this.stopPolling();
        this.pollStartedAt = Date.now();
        this.pollTimerId = window.setInterval(() => this.poll(), POLL_INTERVAL_MS);
    }


    /**
     * Asks whether this automation is still among the running ones.
     *
     * Giving up after the limit leaves `running` false and the list reloaded: a run that takes
     * longer than that is better followed from the list page, and a panel that polls forever is
     * worse than one that stops.
     */
    private poll(): void {
        if (Date.now() - this.pollStartedAt > POLL_LIMIT_MS) {
            this.stopPolling();
            this.running = false;
            this.loadRuns();

            return;
        }

        this.automationsService.getRunningSchedulers()
            .pipe(catchError(() => of([])))
            .subscribe(list => {
                const ids = (Array.isArray(list) ? list : []).map(item => item?.schedulerId);

                if (ids.includes(this.schedulerId)) {
                    return;
                }

                this.stopPolling();
                this.running = false;
                this.afterRun();
            });
    }


    /**
     * Reloads the list and opens the run that just finished.
     *
     * "Just finished" is worked out by difference: whichever run was not in the list before the
     * start is the new one. Reading the newest date instead would open the wrong run whenever the
     * scheduler also fired on its own schedule while this one was running.
     */
    private afterRun(): void {
        const previous = new Set(this.runs.map(run => run.execution_id));

        this.loadRuns(() => {
            const fresh = this.runs.find(run => !previous.has(run.execution_id));

            if (fresh) {
                this.selected = fresh;
            }
        });
    }


    private stopPolling(): void {
        if (this.pollTimerId !== undefined) {
            window.clearInterval(this.pollTimerId);
            this.pollTimerId = undefined;
        }
    }

    /* --------------------------------------------------- GETTERS ---------------------------------------------------- */

    public get canRun(): boolean {
        return !!this.schedulerId;
    }


    public get unsaved(): boolean {
        return !this.schedulerId;
    }


    public formatDate(value: AutomationRunEntry['log_date']): string {
        const ms = this.toMillis(value);

        return ms === null ? '-' : new Date(ms).toLocaleString();
    }


    public trackByRun(index: number, entry: AutomationRunEntry): number {
        return entry.execution_id ?? index;
    }

    /* ------------------------------------------------- COMPUTATION --------------------------------------------------- */

    /** Keeps only entries that name a run, and records which list each came from. */
    private tag(entries: unknown, status: 's' | 'f'): AutomationRunEntry[] {
        return (Array.isArray(entries) ? entries : [])
            .filter(entry => !!entry?.execution_id)
            .map(entry => ({ ...entry, status: entry.status ?? status } as AutomationRunEntry));
    }


    private dateOf(entry: AutomationRunEntry): number {
        return this.toMillis(entry.log_date) ?? 0;
    }


    /** The log date as milliseconds. OpenCelium sends either a string or a Mongo `$date`. */
    private toMillis(value: AutomationRunEntry['log_date']): number | null {
        if (!value) {
            return null;
        }

        const raw = typeof value === 'string' ? value : value?.$date;

        if (raw === undefined || raw === null) {
            return null;
        }

        const ms = new Date(raw).getTime();

        return isNaN(ms) ? null : ms;
    }
}
