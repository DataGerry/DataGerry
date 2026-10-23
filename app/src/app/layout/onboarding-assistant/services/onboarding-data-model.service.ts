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
import { Subscription } from 'rxjs';
import { finalize } from 'rxjs/operators';

import { LoaderService } from '../../../core/services/loader.service';
import { ImportService } from '../../../modules/import/services/import.service';
import { SystemService } from '../../../settings/system/system.service';
import { ConfigurationImportPreview } from '../../../core/models/configuration-transfer.model';
/* ------------------------------------------------------------------------------------------------------------------ */

/** Data model file state of the onboarding assistant; provided by the assistant so it outlives the step view. */
@Injectable()
export class OnboardingDataModelService {
    private readonly importService = inject(ImportService);
    private readonly systemService = inject(SystemService);
    private readonly loaderService = inject(LoaderService);
    private readonly destroyRef = inject(DestroyRef);

    private readonly previewState = signal<ConfigurationImportPreview | null>(null);
    private readonly previewFailedState = signal(false);
    private readonly maxUploadSizeState = signal<number | null>(null);

    public readonly preview = this.previewState.asReadonly();
    public readonly previewFailed = this.previewFailedState.asReadonly();
    public readonly maxUploadSize = this.maxUploadSizeState.asReadonly();

    public readonly isImportable = computed(() => !!this.preview()?.importable);

    private previewRequest: Subscription | null = null;
    private limitsRequested = false;

    /* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    /** Without a known limit the dropzone accepts any size and the backend still refuses an oversized upload. */
    public loadUploadLimit(): void {
        if (this.limitsRequested) {
            return;
        }

        this.limitsRequested = true;
        this.loaderService.show();

        this.systemService.getLimits().pipe(
            takeUntilDestroyed(this.destroyRef),
            finalize(() => this.loaderService.hide())
        ).subscribe({
            next: limits => this.maxUploadSizeState.set(limits?.max_upload_size || null),
            error: () => {
                this.limitsRequested = false;
            }
        });
    }


    /** A preview still running for an earlier file is cancelled. */
    public loadPreview(file: File | null): void {
        this.clear();

        if (!file) {
            return;
        }

        this.loaderService.show();

        this.previewRequest = this.importService.previewDataModel(file).pipe(
            takeUntilDestroyed(this.destroyRef),
            finalize(() => {
                this.previewRequest = null;
                this.loaderService.hide();
            })
        ).subscribe({
            next: preview => this.previewState.set(preview ?? null),
            error: () => this.previewFailedState.set(true)
        });
    }


    public clear(): void {
        this.previewRequest?.unsubscribe();
        this.previewState.set(null);
        this.previewFailedState.set(false);
    }
}
