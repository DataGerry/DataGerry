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
* along with this program.  If not, see <https://www.gnu.org/licenses/>.
*/

import { DOCUMENT, NgOptimizedImage } from '@angular/common';
import { RouterLink } from '@angular/router';
import { CdkTrapFocus } from '@angular/cdk/a11y';
import {
    ChangeDetectionStrategy,
    Component,
    DestroyRef,
    ElementRef,
    computed,
    effect,
    inject,
    signal,
    untracked,
    viewChild
} from '@angular/core';

import { CoreModule } from '../../core/core.module';
import { AuthModule } from '../../modules/auth/auth.module';
import { OnboardingTourService } from './services/onboarding-tour.service';
import { TourChapterProgress, TourChapterState, TourLayout, TourStep } from './models/onboarding-tour.model';
import {
    findVisibleTarget,
    getViewportSize,
    measureCardHeight,
    measureTarget,
    resolveCardPosition,
    resolveCenteredCard,
    resolveSpotlight
} from './utils/onboarding-tour-position.util';
/* ------------------------------------------------------------------------------------------------------------------ */

/** Routed targets render after navigation, so they are looked up for up to two seconds. */
const TARGET_LOOKUP_INTERVAL = 100;
const TARGET_LOOKUP_ATTEMPTS = 20;

/** The navbar reflows after the last resize frame, so the layout is measured once more when it settles. */
const RESIZE_SETTLE_DELAY = 200;

@Component({
    selector: 'cmdb-onboarding-tour',
    templateUrl: './onboarding-tour.component.html',
    styleUrls: ['./onboarding-tour.component.scss'],
    imports: [CdkTrapFocus, NgOptimizedImage, RouterLink, CoreModule, AuthModule],
    changeDetection: ChangeDetectionStrategy.OnPush,
    host: {
        '(window:resize)': 'onViewportChange()',
        '(window:scroll)': 'onViewportChange()',
        '(document:keydown)': 'onKeydown($event)'
    }
})
export class OnboardingTourComponent {
    private readonly document = inject(DOCUMENT);
    private readonly destroyRef = inject(DestroyRef);

    public readonly tour = inject(OnboardingTourService);

    private readonly card = viewChild<ElementRef<HTMLElement>>('card');

    public readonly layout = signal<TourLayout | null>(null);

    /** Progress counts visited steps, so chapters skipped by a jump are not shown as done. */
    public readonly chapters = computed<TourChapterProgress[]>(() => {
        const index = this.tour.currentIndex();
        const visited = this.tour.visited();

        return this.tour.chapters().map(chapter => {
            const endIndex = chapter.startIndex + chapter.stepCount;
            let seen = 0;

            for (let stepIndex = chapter.startIndex; stepIndex < endIndex; stepIndex++) {
                seen += visited.has(stepIndex) ? 1 : 0;
            }

            const isCurrent = index >= chapter.startIndex && index < endIndex;
            const state: TourChapterState = isCurrent ? 'active' : seen === chapter.stepCount ? 'done' : 'upcoming';

            return { ...chapter, state, fill: (seen / chapter.stepCount) * 100 };
        });
    });

    /** Counts the highlighted stops only, so the intro and outro do not inflate the number. */
    public readonly eyebrow = computed(() => {
        const step = this.tour.currentStep();
        const stops = this.tour.steps().filter(item => item.kind === 'spotlight');

        if (!step) {
            return '';
        }

        if (step.kind === 'intro') {
            return `${step.chapter} · About 3 minutes`;
        }

        if (step.kind === 'outro') {
            return step.chapter;
        }

        return `Step ${stops.indexOf(step) + 1} of ${stops.length} · ${step.chapter}`;
    });
    /** Feature tiles the user has the rights for. */
    public readonly features = computed(() =>
        (this.tour.currentStep()?.features ?? []).filter(feature => !feature.right || this.tour.hasRight(feature.right))
    );

    public readonly arrowOffset = computed(() => `${this.layout()?.card.arrowOffset ?? 0}px`);

    public readonly nextLabel = computed(() => {
        if (this.tour.isFirstStep()) {
            return 'Start tour';
        }

        return this.tour.isLastStep() ? 'Finish' : 'Next';
    });

    private target: HTMLElement | null = null;
    private returnFocusTo: HTMLElement | null = null;
    private lookupTimer: ReturnType<typeof setTimeout> | null = null;
    private layoutFrame: number | null = null;
    private settleTimer: ReturnType<typeof setTimeout> | null = null;
    private readonly targetObserver = new ResizeObserver(() => this.scheduleLayout(false));


    constructor() {
        effect(() => {
            const step = this.tour.currentStep();
            untracked(() => this.showStep(step));
        });

        this.destroyRef.onDestroy(() => {
            this.cancelPendingWork();
            this.targetObserver.disconnect();
        });
    }

    /* ---------------------------------------------------- EVENTS ------------------------------------------------------ */

    public onViewportChange(): void {
        if (!this.tour.isActive()) {
            return;
        }

        this.scheduleLayout(false);

        if (this.settleTimer !== null) {
            clearTimeout(this.settleTimer);
        }

        this.settleTimer = setTimeout(() => {
            this.settleTimer = null;
            this.scheduleLayout(false);
        }, RESIZE_SETTLE_DELAY);
    }


    public onKeydown(event: KeyboardEvent): void {
        if (!this.tour.isActive()) {
            return;
        }

        switch (event.key) {
            case 'Escape':
                event.preventDefault();
                this.tour.end();
                break;
            case 'ArrowRight':
                if (!this.tour.isLastStep()) {
                    event.preventDefault();
                    this.tour.next();
                }
                break;
            case 'ArrowLeft':
                if (!this.tour.isFirstStep()) {
                    event.preventDefault();
                    this.tour.previous();
                }
                break;
        }
    }


    public onSecondaryAction(): void {
        if (this.tour.isFirstStep()) {
            this.tour.end();
            return;
        }

        this.tour.previous();
    }

    /* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    private showStep(step: TourStep | null): void {
        this.cancelPendingWork();

        if (!step) {
            this.layout.set(null);
            this.restoreFocus();
            return;
        }

        if (!this.returnFocusTo) {
            this.returnFocusTo = this.document.activeElement as HTMLElement | null;
        }

        this.locateTarget(step, 0);
    }


    /** A target that never shows up falls back to a centered card, so the tour cannot get stuck. */
    private locateTarget(step: TourStep, attempt: number): void {
        const target = step.target
            ? findVisibleTarget(this.document, step.target, getViewportSize(this.document))
            : null;

        if (step.target && !target && attempt < TARGET_LOOKUP_ATTEMPTS) {
            this.lookupTimer = setTimeout(() => this.locateTarget(step, attempt + 1), TARGET_LOOKUP_INTERVAL);
            return;
        }

        this.target = target;

        if (target) {
            target.scrollIntoView({ block: 'nearest', inline: 'nearest' });
            this.targetObserver.observe(target);
        }

        this.scheduleLayout(true);
    }


    private scheduleLayout(moveFocus: boolean): void {
        if (this.layoutFrame !== null) {
            cancelAnimationFrame(this.layoutFrame);
        }

        this.layoutFrame = requestAnimationFrame(() => {
            this.layoutFrame = null;
            this.updateLayout();

            if (moveFocus) {
                this.card()?.nativeElement.focus({ preventScroll: true });
            }
        });
    }


    private updateLayout(): void {
        const cardElement = this.card()?.nativeElement;
        const step = this.tour.currentStep();

        if (!cardElement || !step) {
            return;
        }

        const viewport = getViewportSize(this.document);
        const cardSize = { width: cardElement.offsetWidth, height: measureCardHeight(cardElement) };
        // A resize can hide the target mid-step, e.g. when the navbar collapses.
        const target = step.target ? findVisibleTarget(this.document, step.target, viewport) : null;

        if (!target || target !== this.target) {
            this.layout.set({
                stepId: step.id,
                spotlight: { top: viewport.height / 2, left: viewport.width / 2, width: 0, height: 0 },
                hasTarget: false,
                card: resolveCenteredCard(cardSize, viewport)
            });
            return;
        }

        const spotlight = resolveSpotlight(measureTarget(target, step.include), viewport);

        this.layout.set({
            stepId: step.id,
            spotlight,
            hasTarget: true,
            card: resolveCardPosition(spotlight, cardSize, viewport, step.placement ?? 'bottom')
        });
    }


    private cancelPendingWork(): void {
        if (this.lookupTimer !== null) {
            clearTimeout(this.lookupTimer);
            this.lookupTimer = null;
        }

        if (this.layoutFrame !== null) {
            cancelAnimationFrame(this.layoutFrame);
            this.layoutFrame = null;
        }

        if (this.settleTimer !== null) {
            clearTimeout(this.settleTimer);
            this.settleTimer = null;
        }

        this.targetObserver.disconnect();
        this.target = null;
    }


    private restoreFocus(): void {
        if (this.returnFocusTo?.isConnected) {
            this.returnFocusTo.focus({ preventScroll: true });
        }

        this.returnFocusTo = null;
    }
}
