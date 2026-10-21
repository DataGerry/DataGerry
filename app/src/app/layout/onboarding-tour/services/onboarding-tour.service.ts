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
import { ONBOARDING_TOUR_STEPS } from '../models/onboarding-tour-steps';
import { TourSize, TourStep } from '../models/onboarding-tour.model';
import { findVisibleTarget, getViewportSize } from '../utils/onboarding-tour-position.util';
/* ------------------------------------------------------------------------------------------------------------------ */

@Injectable({ providedIn: 'root' })
export class OnboardingTourService {
    private readonly router = inject(Router);
    private readonly document = inject(DOCUMENT);
    private readonly permissionService = inject(PermissionService);

    private readonly activeSteps = signal<TourStep[]>([]);
    private readonly activeIndex = signal(0);

    public readonly steps = this.activeSteps.asReadonly();
    public readonly currentIndex = this.activeIndex.asReadonly();

    public readonly isActive = computed(() => this.activeSteps().length > 0);
    public readonly currentStep = computed<TourStep | null>(() => this.activeSteps()[this.activeIndex()] ?? null);
    public readonly isFirstStep = computed(() => this.activeIndex() === 0);
    public readonly isLastStep = computed(() => this.activeIndex() === this.activeSteps().length - 1);

    /* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    public start(): void {
        const viewport = getViewportSize(this.document);

        this.activeSteps.set(ONBOARDING_TOUR_STEPS.filter(step => this.isReachable(step, viewport)));
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


    public end(): void {
        this.activeSteps.set([]);
        this.activeIndex.set(0);
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

        this.activeIndex.set(index);
    }
}
