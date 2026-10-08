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
import { forkJoin, Observable, of } from 'rxjs';
import { catchError, finalize } from 'rxjs/operators';
import { NgbModal } from '@ng-bootstrap/ng-bootstrap';

import { AutomationsService } from '../../services/automations.service';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { AutomationRunEntry } from '../../models/automation-run-log.model';
import {
    SaveBeforeRunChoice,
    SaveBeforeRunModalComponent
} from '../save-before-run-modal/save-before-run-modal.component';
/* ------------------------------------------------------------------------------------------------------------------ */

/** How often the panel asks whether the run it started has finished. */
const POLL_INTERVAL_MS = 3000;

/**
 * When to stop asking, at the least. A run expected to take longer is followed for three times its
 * expected length; one that outlives that is still running - the panel just stops chasing it.
 */
const POLL_LIMIT_MS = 10 * 60 * 1000;

/** How often the progress bar moves. */
const TICK_MS = 500;

/** Where the bar stops while the run has not reported back: full means finished, and it is not. */
const PROGRESS_CEILING = 95;

/**
 * Where "always save before a run" is remembered. Per browser, like the list's auto-refresh: it is
 * a habit of whoever sits at this screen, not a property of any automation.
 */
const ALWAYS_SAVE_STORAGE_KEY = 'automations.run.alwaysSaveBeforeRun';


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

    /** Whether the editor holds changes a run would not execute. */
    @Input() public unsavedChanges = false;

    /** Whether those changes can be saved right now; they cannot while they do not validate. */
    @Input() public canSaveChanges = true;

    /**
     * Saves the changes without leaving the editor. Without it the panel only runs what is stored
     * and asks nothing, which is what a caller that edits nothing wants.
     */
    @Input() public saveChanges: (() => Observable<void>) | null = null;

    public runs: AutomationRunEntry[] = [];
    public selected: AutomationRunEntry | null = null;
    public loadingRuns = false;
    public starting = false;
    public running = false;
    public listError = '';

    private pollTimerId?: number;
    private pollStartedAt = 0;
    private tickTimerId?: number;

    /** How long a run of this automation took last time, in ms; null until that is known. */
    public expectedMs: number | null = null;

    /** How long the run being followed has taken so far. */
    public elapsedMs = 0;
    private runStartedAt = 0;

    private readonly automationsService = inject(AutomationsService);
    private readonly toast = inject(ToastService);
    private readonly modalService = inject(NgbModal);

    /** Read once: the setting only changes through this panel, which keeps it in step. */
    public alwaysSave = this.readAlwaysSave();

    /* -------------------------------------------------- LIFE CYCLE -------------------------------------------------- */

    public ngOnChanges(changes: SimpleChanges): void {
        if (changes['schedulerId']) {
            this.selected = null;
            this.runs = [];
            this.loadRuns();
            this.loadExpectedDuration();
            this.resumeIfRunning();
        }
    }


    public ngOnDestroy(): void {
        this.stopPolling();
        this.stopTicker();
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
     *
     * With unsaved changes on screen the run would test the previous version, so the user is asked
     * first - unless they chose to always save, and the changes can be saved.
     */
    public start(): void {
        if (!this.schedulerId || this.starting || this.running) {
            return;
        }

        if (!this.unsavedChanges || !this.saveChanges) {
            this.execute();

            return;
        }

        if (this.alwaysSave && this.canSaveChanges) {
            this.saveThenExecute();

            return;
        }

        const modalRef = this.modalService.open(SaveBeforeRunModalComponent);
        modalRef.componentInstance.canSave = this.canSaveChanges;

        modalRef.result.then(
            (choice: SaveBeforeRunChoice) => {
                if (choice.action === 'run-saved') {
                    this.execute();

                    return;
                }

                if (choice.remember) {
                    this.setAlwaysSave(true);
                }

                this.saveThenExecute();
            },
            () => undefined
        );
    }


    /** Turns "always save before a run" off again, so the next run asks. */
    public askAgain(): void {
        this.setAlwaysSave(false);
    }


    /** Saves first and runs only once that succeeded - a failed save must not run the old version. */
    private saveThenExecute(): void {
        this.starting = true;

        this.saveChanges!().subscribe({
            next: () => {
                this.toast.success('The changes were saved.');
                this.starting = false;
                this.execute();
            },
            error: err => {
                this.starting = false;
                this.toast.error(err?.error?.message || 'The changes could not be saved, so the automation was not started.');
            }
        });
    }


    private execute(): void {
        const schedulerId = this.schedulerId;

        if (!schedulerId) {
            return;
        }

        this.starting = true;

        this.automationsService.executeScheduler(schedulerId)
            .pipe(finalize(() => {
                this.starting = false;
            }))
            .subscribe({
                next: () => {
                    this.toast.success('The automation was started. It keeps running if you leave this page.');
                    this.markRunning();
                },
                error: err => {
                    // A start that answers with an error may still have started the run - a slow
                    // answer is one. Whether it runs is what counts, so that is asked first.
                    this.automationsService.getRunningSchedulers()
                        .pipe(catchError(() => of([])))
                        .subscribe(list => {
                            if (this.isListedAsRunning(list)) {
                                this.toast.success('The automation was started.');
                                this.markRunning();
                            } else {
                                this.toast.error(err?.error?.message || 'The automation could not be started.');
                            }
                        });
                }
            });
    }


    public select(entry: AutomationRunEntry): void {
        this.selected = this.selected?.execution_id === entry.execution_id ? null : entry;
    }


    public isSelected(entry: AutomationRunEntry): boolean {
        return this.selected?.execution_id === entry.execution_id;
    }

    /* --------------------------------------------------- PROGRESS --------------------------------------------------- */

    /**
     * How far the run probably is, 0 to 100.
     *
     * OpenCelium reports nothing while a run is going on, so this is time measured against how long
     * the last run took. It stops short of full until the run is over; without a previous run it
     * creeps towards that mark, so it moves without pretending to know.
     */
    public get progress(): number {
        if (this.expectedMs && this.expectedMs > 0) {
            return Math.min(PROGRESS_CEILING, (this.elapsedMs / this.expectedMs) * 100);
        }

        return PROGRESS_CEILING * (1 - Math.exp(-this.elapsedMs / 30000));
    }


    public get progressText(): string {
        const elapsed = formatSeconds(this.elapsedMs);

        if (!this.expectedMs) {
            return `${elapsed} so far`;
        }

        if (this.elapsedMs > this.expectedMs * 1.1) {
            return `${elapsed} - longer than the last run (${formatSeconds(this.expectedMs)})`;
        }

        return `${elapsed} of about ${formatSeconds(this.expectedMs)}`;
    }


    /** Reads how long the last run took, which is what the progress bar measures against. */
    private loadExpectedDuration(): void {
        const schedulerId = this.schedulerId;

        if (!schedulerId) {
            this.expectedMs = null;

            return;
        }

        this.automationsService.getScheduler(schedulerId)
            .pipe(catchError(() => of(null)))
            .subscribe(scheduler => {
                if (scheduler && schedulerId === this.schedulerId) {
                    this.expectedMs = lastDurationOf(scheduler) ?? this.expectedMs;
                }
            });
    }


    /** Picks up a run that was already going when the panel opened - started elsewhere, or before leaving. */
    private resumeIfRunning(): void {
        if (!this.schedulerId || this.running) {
            return;
        }

        this.automationsService.getRunningSchedulers()
            .pipe(catchError(() => of([])))
            .subscribe(list => {
                if (this.isListedAsRunning(list) && !this.running) {
                    this.markRunning();
                }
            });
    }


    private markRunning(): void {
        this.running = true;
        this.runStartedAt = Date.now();
        this.elapsedMs = 0;
        this.startTicker();
        this.beginPolling();
    }


    private startTicker(): void {
        this.stopTicker();
        this.tickTimerId = window.setInterval(() => {
            this.elapsedMs = Date.now() - this.runStartedAt;
        }, TICK_MS);
    }


    private stopTicker(): void {
        if (this.tickTimerId !== undefined) {
            window.clearInterval(this.tickTimerId);
            this.tickTimerId = undefined;
        }
    }


    private isListedAsRunning(list: unknown): boolean {
        const entries = Array.isArray(list) ? list : [];
        const own = entries.find(item => item?.schedulerId === this.schedulerId);

        // The running list knows an average, which is the next best thing to the last run.
        if (own && !this.expectedMs && typeof own.avgDuration === 'number' && own.avgDuration > 0) {
            this.expectedMs = own.avgDuration;
        }

        return !!own;
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
        const limit = Math.max(POLL_LIMIT_MS, (this.expectedMs ?? 0) * 3);

        if (Date.now() - this.pollStartedAt > limit) {
            this.stopPolling();
            this.stopTicker();
            this.running = false;
            this.loadRuns();

            return;
        }

        this.automationsService.getRunningSchedulers()
            .pipe(catchError(() => of([])))
            .subscribe(list => {
                if (this.isListedAsRunning(list)) {
                    return;
                }

                this.stopPolling();
                this.stopTicker();
                this.running = false;
                this.afterRun();
                this.loadExpectedDuration();
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

    /* -------------------------------------------------- PREFERENCE -------------------------------------------------- */

    /** Storage can be unavailable (private windows, blocked site data); then the panel just asks. */
    private readAlwaysSave(): boolean {
        try {
            return window.localStorage.getItem(ALWAYS_SAVE_STORAGE_KEY) === 'true';
        } catch {
            return false;
        }
    }


    private setAlwaysSave(value: boolean): void {
        this.alwaysSave = value;

        try {
            if (value) {
                window.localStorage.setItem(ALWAYS_SAVE_STORAGE_KEY, 'true');
            } else {
                window.localStorage.removeItem(ALWAYS_SAVE_STORAGE_KEY);
            }
        } catch {
            // Kept for this visit only.
        }
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


/** How long the scheduler's last run took, in ms: the last successful one, else the last failed one. */
function lastDurationOf(scheduler: any): number | null {
    const success = scheduler?.lastExecution?.success?.duration;
    const fail = scheduler?.lastExecution?.fail?.duration;
    const duration = typeof success === 'number' && success > 0 ? success : fail;

    return typeof duration === 'number' && duration > 0 ? duration : null;
}


/** 4 s, 1 min 20 s, 1 h 5 min - as precise as a person reading a progress bar wants it. */
function formatSeconds(ms: number): string {
    const seconds = Math.max(0, Math.round(ms / 1000));

    if (seconds < 60) {
        return `${seconds} s`;
    }

    const minutes = Math.floor(seconds / 60);

    if (minutes < 60) {
        return seconds % 60 ? `${minutes} min ${seconds % 60} s` : `${minutes} min`;
    }

    return `${Math.floor(minutes / 60)} h ${minutes % 60} min`;
}
