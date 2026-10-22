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

import { ChangeDetectionStrategy, Component, DestroyRef, OnInit, computed, inject, input, model } from '@angular/core';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';

import { NgbModal } from '@ng-bootstrap/ng-bootstrap';

import { CoreModule } from '../../../../core/core.module';
import { OnboardingBestPracticeService } from '../../services/onboarding-best-practice.service';
import { IMPORT_OPTIONS, OnboardingImportSource } from '../../models/onboarding-assistant.model';
import {
    BestPracticeModelCard,
    BestPracticeModelDetails,
    MODEL_DETAILS_TITLE_ID
} from '../../models/onboarding-best-practice.model';
import { toModelCardView } from '../../utils/onboarding-best-practice.util';
import { OnboardingModelDetailsComponent } from '../model-details/onboarding-model-details.component';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'cmdb-onboarding-import-step',
    templateUrl: './onboarding-import-step.component.html',
    styleUrls: ['./onboarding-import-step.component.scss'],
    imports: [ReactiveFormsModule, CoreModule],
    changeDetection: ChangeDetectionStrategy.OnPush
})
export class OnboardingImportStepComponent implements OnInit {
    public readonly bestPractice = inject(OnboardingBestPracticeService);
    private readonly modalService = inject(NgbModal);
    private readonly destroyRef = inject(DestroyRef);

    public readonly selectedSource = model<OnboardingImportSource | null>(null);

    /** Owned by the assistant so the file survives moving between steps. */
    public readonly dataModelFile = input.required<FormControl<File | null>>();

    /** Applying a best-practice model is refused for anyone but the administrator account. */
    public readonly canImport = input(false);

    public readonly importOptions = computed(() =>
        IMPORT_OPTIONS.filter(option => option.id !== 'best-practice' || this.canImport())
    );

    public readonly modelCards = computed(() => (this.bestPractice.models() ?? []).map(toModelCardView));

    /* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    public ngOnInit(): void {
        if (this.selectedSource() === 'best-practice') {
            this.bestPractice.loadModels();
        }
    }

    /* ---------------------------------------------------- EVENTS ------------------------------------------------------ */

    public onSourceSelected(source: OnboardingImportSource): void {
        this.selectedSource.set(source);

        if (source === 'best-practice') {
            this.bestPractice.loadModels();
        }
    }


    public onModelSelected(modelId: string): void {
        this.bestPractice.selectModel(modelId);
    }


    public onRetryModels(): void {
        this.bestPractice.loadModels();
    }


    public onViewDetails(card: BestPracticeModelCard): void {
        this.bestPractice.loadDetails(card.model_id).pipe(
            takeUntilDestroyed(this.destroyRef)
        ).subscribe(details => this.openDetails(details));
    }

    /* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    private openDetails(details: BestPracticeModelDetails): void {
        const modalRef = this.modalService.open(OnboardingModelDetailsComponent, {
            centered: true,
            size: 'lg',
            windowClass: 'dg-modal-window',
            backdropClass: 'dg-modal-window-backdrop',
            ariaLabelledBy: MODEL_DETAILS_TITLE_ID
        });

        modalRef.componentInstance.details.set(details);
        modalRef.componentInstance.isSelected.set(this.bestPractice.selectedModelId() === details.model_id);

        modalRef.result.then((result: unknown) => {
            if (result === 'select') {
                this.bestPractice.selectModel(details.model_id);
            }
        }, () => { });
    }
}
