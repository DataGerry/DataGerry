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
import { HttpErrorResponse } from '@angular/common/http';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { throwError } from 'rxjs';
import { finalize, switchMap } from 'rxjs/operators';

import { FileSaverService } from 'ngx-filesaver';

import { LoaderService } from '../../../core/services/loader.service';
import { ToastService } from '../../toast/toast.service';
import { LicenseService } from '../../../settings/license-management/services/license.service';
import { PremiumFeatureService } from '../../../settings/license-management/premium-feature/premium-feature.service';
import { readLicenseFile } from '../../../settings/license-management/utils/license.util';
import {
    ACTIVATION_REQUEST_FILENAME,
    CurrentLicense,
    LICENSE_TIER_LABELS,
    LicenseTier
} from '../../../settings/license-management/models/license.model';
import {
    ActivationPhase,
    ActivationRequestFile,
    EMPTY_LICENSE_FILE_MESSAGE,
    LICENSE_IMPORT_FAILED_MESSAGE,
    OnboardingLicenseStatus
} from '../models/onboarding-license.model';
/* ------------------------------------------------------------------------------------------------------------------ */

/** License activation state of the onboarding assistant; provided by the assistant so it outlives the step view. */
@Injectable()
export class OnboardingLicenseService {
    private readonly licenseService = inject(LicenseService);
    private readonly premiumFeatureService = inject(PremiumFeatureService);
    private readonly loaderService = inject(LoaderService);
    private readonly toastService = inject(ToastService);
    private readonly fileSaver = inject(FileSaverService);
    private readonly destroyRef = inject(DestroyRef);

    private readonly phaseState = signal(ActivationPhase.Request);
    private readonly activationRequestState = signal<ActivationRequestFile | null>(null);
    private readonly licenseState = signal<CurrentLicense | null>(null);
    private readonly importErrorState = signal<string | null>(null);
    private readonly importingState = signal(false);
    private readonly isSkipped = signal(false);

    public readonly phase = this.phaseState.asReadonly();
    public readonly activationRequest = this.activationRequestState.asReadonly();
    public readonly license = this.licenseState.asReadonly();
    public readonly importError = this.importErrorState.asReadonly();
    public readonly isImporting = this.importingState.asReadonly();

    private hasCheckedCurrentLicense = false;

    public readonly isActive = computed(() => !!this.license()?.is_active);

    public readonly status = computed<OnboardingLicenseStatus>(() => {
        if (this.isActive()) {
            return 'active';
        }

        return this.isSkipped() ? 'skipped' : 'none';
    });

    public readonly tierLabel = computed(() => {
        const type = this.license()?.entitlement.type as LicenseTier;
        return LICENSE_TIER_LABELS[type] ?? '';
    });

    /* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    /** A license can survive a workspace reset, so an active one is picked up instead of activated again. */
    public loadCurrentLicense(): void {
        if (this.hasCheckedCurrentLicense) {
            return;
        }

        this.hasCheckedCurrentLicense = true;
        this.loaderService.show();

        this.licenseService.getCurrentLicense().pipe(
            takeUntilDestroyed(this.destroyRef),
            finalize(() => this.loaderService.hide())
        ).subscribe({
            next: license => {
                if (license.is_active) {
                    this.licenseState.set(license);
                }
            },
            error: () => {
                this.hasCheckedCurrentLicense = false;
                this.toastService.error('The current license could not be loaded.');
            }
        });
    }


    public createActivationRequest(): void {
        this.loaderService.show();

        this.licenseService.generateActivationKey().pipe(
            takeUntilDestroyed(this.destroyRef),
            finalize(() => this.loaderService.hide())
        ).subscribe({
            next: key => this.onActivationRequestCreated(key),
            error: () => this.toastService.error('The activation request could not be created.')
        });
    }


    public downloadActivationRequest(): void {
        const request = this.activationRequest();

        if (!request) {
            return;
        }

        const blob = new Blob([request.content], { type: 'text/plain;charset=utf-8' });
        this.fileSaver.save(blob, ACTIVATION_REQUEST_FILENAME);
    }


    public continueWithExistingRequest(): void {
        this.phaseState.set(ActivationPhase.Portal);
    }


    public confirmLicenseFileReceived(): void {
        this.phaseState.set(ActivationPhase.Import);
    }


    public importLicense(file: File): void {
        if (this.isImporting()) {
            return;
        }

        this.importingState.set(true);
        this.importErrorState.set(null);
        this.loaderService.show();

        readLicenseFile(file).pipe(
            switchMap(content => {
                const blob = content.trim();
                return blob
                    ? this.licenseService.importLicense(blob)
                    : throwError(() => new Error(EMPTY_LICENSE_FILE_MESSAGE));
            }),
            takeUntilDestroyed(this.destroyRef),
            finalize(() => {
                this.importingState.set(false);
                this.loaderService.hide();
            })
        ).subscribe({
            next: license => this.onLicenseImported(license),
            error: (error: unknown) => this.importErrorState.set(this.resolveImportError(error))
        });
    }


    public clearImportError(): void {
        this.importErrorState.set(null);
    }


    public skip(): void {
        if (!this.isActive()) {
            this.isSkipped.set(true);
        }
    }


    public clearSkip(): void {
        this.isSkipped.set(false);
    }

    /* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    private onActivationRequestCreated(key: string): void {
        const content = (key ?? '').trim();

        if (!content) {
            this.toastService.error('The activation request could not be created.');
            return;
        }

        this.activationRequestState.set({ content, size: new Blob([content]).size, createdAt: Date.now() });
        this.importErrorState.set(null);
        this.phaseState.set(ActivationPhase.Portal);
        this.toastService.success('Request file created.');
    }


    private onLicenseImported(license: CurrentLicense): void {
        if (!license.is_active) {
            this.importErrorState.set(LICENSE_IMPORT_FAILED_MESSAGE);
            return;
        }

        this.licenseState.set(license);
        this.isSkipped.set(false);
        this.toastService.success(`License imported: ${this.tierLabel()}`);

        this.loaderService.show();

        this.premiumFeatureService.refresh().pipe(
            takeUntilDestroyed(this.destroyRef),
            finalize(() => this.loaderService.hide())
        ).subscribe();
    }


    /** A 400 names why the license was refused; any other failure stays generic. */
    private resolveImportError(error: unknown): string {
        if (error instanceof HttpErrorResponse) {
            return (error.status === 400 && error.error?.message) || LICENSE_IMPORT_FAILED_MESSAGE;
        }

        return error instanceof Error && error.message === EMPTY_LICENSE_FILE_MESSAGE
            ? EMPTY_LICENSE_FILE_MESSAGE
            : LICENSE_IMPORT_FAILED_MESSAGE;
    }
}
