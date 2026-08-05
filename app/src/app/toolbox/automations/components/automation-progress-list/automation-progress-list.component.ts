import { Component, inject, EventEmitter, Input, Output, SimpleChanges } from '@angular/core';

import { AutomationsService } from '../../services/automations.service';

type RunningScheduler = {
  schedulerId: number;
  title: string;
  avgDuration?: number;
  startedAt: number;
  expectedDurationMs: number;
  elapsedMs: number;
  progress: number;
};

@Component({
  selector: 'app-automation-progress-list',
  templateUrl: './automation-progress-list.component.html',
  styleUrls: ['./automation-progress-list.component.scss'],
  standalone: false
})
export class AutomationProgressListComponent {
  @Input() automations: any[] = [];
  @Input() refreshToken = 0;
  @Output() runningSchedulerIdsChange = new EventEmitter<number[]>();

  public runningSchedulers: RunningScheduler[] = [];
  private readonly defaultRunningDurationMs = 60000;
  private readonly progressUpdateMs = 250;
  private progressTimerId?: number;
  private runningCheckTimers = new Map<number, number>();

  private readonly automationsService = inject(AutomationsService);

  ngOnInit(): void {
    this.loadRunningSchedulers();
  }

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['refreshToken'] && !changes['refreshToken'].firstChange) {
      this.loadRunningSchedulers();
    }
    if (changes['automations'] && this.runningSchedulers.length) {
      this.syncExpectedDurationsFromAutomations();
    }
  }

  ngOnDestroy(): void {
    this.stopProgressUpdates();
    this.clearRunningCheckTimers();
  }

  trackByRunningScheduler(index: number, item: RunningScheduler): number {
    return item.schedulerId ?? index;
  }

  private loadRunningSchedulers(resetSchedulerIds?: Set<number>): void {
    this.automationsService?.getRunningSchedulers()?.subscribe({
      next: (response) => {
        const list = Array.isArray(response) ? response : [];
        const now = Date.now();
        const existing = new Map(
          this.runningSchedulers.map((item) => [item.schedulerId, item])
        );
        const nextSchedulers = list.map((item) => {
          const previous = existing.get(item.schedulerId);
          const lastDurationMs = this.getLastDurationMs(item.schedulerId);
          const avgDuration =
            typeof item.avgDuration === 'number' && item.avgDuration > 0
              ? item.avgDuration
              : previous?.avgDuration;
          let expectedDurationMs =
            previous?.expectedDurationMs ??
            this.getInitialExpectedDurationMs(lastDurationMs, avgDuration);
          let startedAt = previous?.startedAt ?? now;
          if (resetSchedulerIds?.has(item.schedulerId)) {
            startedAt = now;
            expectedDurationMs = this.getExpectedDurationMs(avgDuration);
          }
          if (!expectedDurationMs || expectedDurationMs <= 0) {
            expectedDurationMs = this.defaultRunningDurationMs;
          }
          const elapsedMs = Math.max(0, now - startedAt);
          const progress = this.getProgressValue(
            previous?.progress ?? 0,
            elapsedMs,
            expectedDurationMs
          );
          return {
            schedulerId: item.schedulerId,
            title: item.title || 'Automation',
            avgDuration,
            startedAt,
            expectedDurationMs,
            elapsedMs,
            progress
          };
        });

        this.runningSchedulers = nextSchedulers;
        this.emitRunningSchedulerIds();
        this.syncRunningCheckTimers();
        this.syncProgressUpdates();
      },
      error: () => {
        this.runningSchedulers = [];
        this.emitRunningSchedulerIds();
        this.syncRunningCheckTimers();
        this.syncProgressUpdates();
      }
    });
  }

  private emitRunningSchedulerIds(): void {
    this.runningSchedulerIdsChange.emit(
      this.runningSchedulers.map((item) => item.schedulerId)
    );
  }

  private syncExpectedDurationsFromAutomations(): void {
    const updated = this.runningSchedulers.map((item) => {
      const lastDurationMs = this.getLastDurationMs(item.schedulerId);
      if (typeof lastDurationMs === 'number' && lastDurationMs > 0) {
        const expectedDurationMs = lastDurationMs;
        const elapsedMs = Math.max(0, Date.now() - item.startedAt);
        const progress = this.getProgressValue(
          item.progress,
          elapsedMs,
          expectedDurationMs
        );
        return {
          ...item,
          expectedDurationMs,
          elapsedMs,
          progress
        };
      }
      return item;
    });
    this.runningSchedulers = updated;
    this.syncRunningCheckTimers();
  }

  private getInitialExpectedDurationMs(
    lastDurationMs: number | null,
    avgDuration?: number
  ): number {
    if (typeof lastDurationMs === 'number' && lastDurationMs > 0) {
      return lastDurationMs;
    }
    return this.getExpectedDurationMs(avgDuration);
  }

  private getExpectedDurationMs(avgDuration?: number): number {
    if (avgDuration === 0) {
      return 5000;
    }
    if (typeof avgDuration === 'number' && avgDuration > 0) {
      return Math.round(avgDuration);
    }
    return this.defaultRunningDurationMs;
  }

  private getLastDurationMs(schedulerId: number): number | null {
    const automation = this.automations.find(
      (item) => item?.schedulerId === schedulerId
    );
    const success = automation?.lastExecution?.success;
    const fail = automation?.lastExecution?.fail;
    if (success?.duration) {
      return success.duration;
    }
    if (fail?.duration) {
      return fail.duration;
    }
    return null;
  }

  private syncRunningCheckTimers(): void {
    const runningIds = new Set(
      this.runningSchedulers.map((item) => item.schedulerId)
    );
    for (const [schedulerId, timerId] of this.runningCheckTimers.entries()) {
      if (!runningIds.has(schedulerId)) {
        window.clearTimeout(timerId);
        this.runningCheckTimers.delete(schedulerId);
      }
    }
    for (const item of this.runningSchedulers) {
      const now = Date.now();
      const remainingMs = Math.max(0, item.expectedDurationMs - (now - item.startedAt));
      this.scheduleRunningCheck(item.schedulerId, remainingMs);
    }
  }

  private scheduleRunningCheck(schedulerId: number, delayMs: number): void {
    const existing = this.runningCheckTimers.get(schedulerId);
    if (existing) {
      window.clearTimeout(existing);
    }
    const timerId = window.setTimeout(() => {
      this.loadRunningSchedulers(new Set([schedulerId]));
    }, delayMs);
    this.runningCheckTimers.set(schedulerId, timerId);
  }

  private clearRunningCheckTimers(): void {
    for (const timerId of this.runningCheckTimers.values()) {
      window.clearTimeout(timerId);
    }
    this.runningCheckTimers.clear();
  }

  private syncProgressUpdates(): void {
    if (this.runningSchedulers.length) {
      this.startProgressUpdates();
    } else {
      this.stopProgressUpdates();
    }
  }

  private startProgressUpdates(): void {
    if (this.progressTimerId) {
      return;
    }
    this.progressTimerId = window.setInterval(() => {
      this.updateRunningProgress();
    }, this.progressUpdateMs);
  }

  private stopProgressUpdates(): void {
    if (this.progressTimerId) {
      window.clearInterval(this.progressTimerId);
      this.progressTimerId = undefined;
    }
  }

  private updateRunningProgress(): void {
    if (!this.runningSchedulers.length) {
      return;
    }
    const now = Date.now();
    this.runningSchedulers = this.runningSchedulers.map((item) => {
      const elapsedMs = Math.max(0, now - item.startedAt);
      const progress = this.getProgressValue(
        item.progress,
        elapsedMs,
        item.expectedDurationMs
      );
      return {
        ...item,
        elapsedMs,
        progress
      };
    });
  }

  private getProgressValue(
    previousProgress: number,
    elapsedMs: number,
    expectedDurationMs: number
  ): number {
    if (!expectedDurationMs || expectedDurationMs <= 0) {
      return previousProgress;
    }
    const computed = Math.min(100, (elapsedMs / expectedDurationMs) * 100);
    return Math.min(100, Math.max(previousProgress, computed));
  }
}
