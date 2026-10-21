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

import { DOCUMENT } from '@angular/common';
import { Injectable, computed, inject, signal } from '@angular/core';
import { Router } from '@angular/router';

import { PermissionService } from '../../../modules/auth/services/permission.service';
import { ONBOARDING_TOUR_CHAPTERS, ONBOARDING_TOUR_STEPS } from '../models/onboarding-tour-steps';
import { TourChapterRange, TourDirection, TourSize, TourStep } from '../models/onboarding-tour.model';
import { findVisibleTarget, getViewportSize } from '../utils/onboarding-tour-position.util';
/* ------------------------------------------------------------------------------------------------------------------ */

@Injectable({ providedIn: 'root' })
export class OnboardingTourService {
    private readonly router = inject(Router);
    private readonly document = inject(DOCUMENT);
    private readonly permissionService = inject(PermissionService);

    private readonly activeSteps = signal<TourStep[]>([]);
    private readonly activeIndex = signal(0);
    private readonly lastDirection = signal<TourDirection>('forward');
    private readonly visitedIndexes = signal<ReadonlySet<number>>(new Set());

    public readonly steps = this.activeSteps.asReadonly();
    public readonly currentIndex = this.activeIndex.asReadonly();
    public readonly direction = this.lastDirection.asReadonly();
    public readonly visited = this.visitedIndexes.asReadonly();

    public readonly isActive = computed(() => this.activeSteps().length > 0);
    public readonly currentStep = computed<TourStep | null>(() => this.activeSteps()[this.activeIndex()] ?? null);
    public readonly isFirstStep = computed(() => this.activeIndex() === 0);
    public readonly isLastStep = computed(() => this.activeIndex() === this.activeSteps().length - 1);

    /** Chapters without a reachable step are left out. */
    public readonly chapters = computed<TourChapterRange[]>(() => {
        const steps = this.activeSteps();

        return ONBOARDING_TOUR_CHAPTERS
            .map(chapter => ({
                ...chapter,
                startIndex: steps.findIndex(step => step.chapter === chapter.title),
                stepCount: steps.filter(step => step.chapter === chapter.title).length
            }))
            .filter(chapter => chapter.stepCount > 0);
    });

    /* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    public start(): void {
        const viewport = getViewportSize(this.document);

        this.activeSteps.set(ONBOARDING_TOUR_STEPS.filter(step => this.isReachable(step, viewport)));
        this.visitedIndexes.set(new Set());
        this.goTo(0);
    }


    public next(): void {
        if (this.isLastStep()) {
            this.end();
            return;
        }

        this.goTo(this.activeIndex() + 1);
    }


    public previous(): void {
        if (!this.isFirstStep()) {
            this.goTo(this.activeIndex() - 1);
        }
    }


    public goToChapter(chapter: TourChapterRange): void {
        if (chapter.startIndex !== this.activeIndex()) {
            this.goTo(chapter.startIndex);
        }
    }


    public end(): void {
        this.activeSteps.set([]);
        this.activeIndex.set(0);
        this.lastDirection.set('forward');
        this.visitedIndexes.set(new Set());
    }


    /** Same check as the route's PermissionGuard; a list needs every right. */
    public hasRight(rights: string | string[]): boolean {
        return [rights].flat().every(right =>
            this.permissionService.hasRight(right) || this.permissionService.hasExtendedRight(right)
        );
    }

    /* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    /** Targets of other pages are not rendered yet; a rendered target must be visible (rights, collapsed navbar). */
    private isReachable(step: TourStep, viewport: TourSize): boolean {
        if (step.right && !this.hasRight(step.right)) {
            return false;
        }

        if (!step.target || !this.document.querySelector(step.target)) {
            return true;
        }

        return !!findVisibleTarget(this.document, step.target, viewport);
    }


    private goTo(index: number): void {
        const route = this.activeSteps()[index]?.route;

        if (route && this.router.url !== route) {
            this.router.navigateByUrl(route);
        }

        this.lastDirection.set(index < this.activeIndex() ? 'backward' : 'forward');
        this.visitedIndexes.update(visited => new Set(visited).add(index));
        this.activeIndex.set(index);
    }
}
