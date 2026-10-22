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

import { DestroyRef, Injectable, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { EMPTY, Observable, Subscription, defer, of } from 'rxjs';
import { catchError, finalize, tap } from 'rxjs/operators';

import { LoaderService } from '../../../core/services/loader.service';
import { ToastService } from '../../toast/toast.service';
import { CurrentLicense } from '../../../settings/license-management/models/license.model';
import { OnboardingLicenseService } from './onboarding-license.service';
import { OnboardingWorkspaceService } from './onboarding-workspace.service';
import { BestPracticeModelCard, BestPracticeModelDetails } from '../models/onboarding-best-practice.model';
/* ------------------------------------------------------------------------------------------------------------------ */

/** Best-practice model state of the onboarding assistant; provided by the assistant so it outlives the step view. */
@Injectable()
export class OnboardingBestPracticeService {
    private readonly workspaceService = inject(OnboardingWorkspaceService);
    private readonly licenseState = inject(OnboardingLicenseService);
    private readonly loaderService = inject(LoaderService);
    private readonly toastService = inject(ToastService);
    private readonly destroyRef = inject(DestroyRef);

    private readonly modelsState = signal<BestPracticeModelCard[] | null>(null);
    private readonly loadFailedState = signal(false);
    private readonly selectedModelIdState = signal<string | null>(null);

    public readonly models = this.modelsState.asReadonly();
    public readonly loadFailed = this.loadFailedState.asReadonly();
    public readonly selectedModelId = this.selectedModelIdState.asReadonly();

    public readonly selectedModel = computed(() =>
        this.models()?.find(model => model.model_id === this.selectedModelId() && model.applicable) ?? null
    );

    private readonly detailsCache = new Map<string, BestPracticeModelDetails>();
    private modelsRequest: Subscription | null = null;

    /** The license the cards are judged against; activating one later can make more models applicable. */
    private modelsLicense: CurrentLicense | null | undefined;

    /* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    /** Skipped while the cards for the current license are loaded or loading; a stale request is cancelled. */
    public loadModels(): void {
        const license = this.licenseState.license();
        const isCurrent = this.modelsLicense === license;

        if (isCurrent && (this.modelsRequest || (this.models() && !this.loadFailed()))) {
            return;
        }

        this.modelsRequest?.unsubscribe();
        this.modelsLicense = license;
        this.loadFailedState.set(false);
        this.loaderService.show();

        this.modelsRequest = this.workspaceService.getBestPracticeModels().pipe(
            takeUntilDestroyed(this.destroyRef),
            finalize(() => {
                this.modelsRequest = null;
                this.loaderService.hide();
            })
        ).subscribe({
            next: models => this.onModelsLoaded(models),
            error: () => this.loadFailedState.set(true)
        });
    }


    public selectModel(modelId: string): void {
        if (this.models()?.some(model => model.model_id === modelId && model.applicable)) {
            this.selectedModelIdState.set(modelId);
        }
    }


    /** Completes without a value when the request fails; the error is shown as a toast. */
    public loadDetails(modelId: string): Observable<BestPracticeModelDetails> {
        const cached = this.detailsCache.get(modelId);

        if (cached) {
            return of(cached);
        }

        return defer(() => {
            this.loaderService.show();
            return this.workspaceService.getBestPracticeModel(modelId);
        }).pipe(
            tap(details => this.detailsCache.set(modelId, details)),
            catchError(() => {
                this.toastService.error('The model details could not be loaded.');
                return EMPTY;
            }),
            finalize(() => this.loaderService.hide())
        );
    }

    /* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    private onModelsLoaded(models: BestPracticeModelCard[]): void {
        this.detailsCache.clear();
        this.modelsState.set(models);

        if (!this.selectedModel()) {
            this.selectedModelIdState.set(null);
        }
    }
}
