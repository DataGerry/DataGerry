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

import {
    ChangeDetectionStrategy,
    Component,
    DestroyRef,
    ElementRef,
    Injector,
    OnInit,
    afterNextRender,
    afterRenderEffect,
    computed,
    inject,
    input,
    linkedSignal,
    model,
    viewChild
} from '@angular/core';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { takeUntilDestroyed, toObservable, toSignal } from '@angular/core/rxjs-interop';
import { startWith, switchMap } from 'rxjs';

import { NgbModal } from '@ng-bootstrap/ng-bootstrap';

import { CoreModule } from '../../../../core/core.module';
import { formatFileSize } from '../../../../core/utils/file-size.util';
import { OnboardingBestPracticeService } from '../../services/onboarding-best-practice.service';
import { OnboardingDataModelService } from '../../services/onboarding-data-model.service';
import { DATA_MODEL_COUNT_LABELS, IMPORT_OPTIONS, OnboardingImportSource } from '../../models/onboarding-assistant.model';
import {
    BestPracticeModelCard,
    BestPracticeModelDetails,
    MODEL_DETAILS_TITLE_ID
} from '../../models/onboarding-best-practice.model';
import { toModelCardView } from '../../utils/onboarding-best-practice.util';
import { OnboardingModelDetailsComponent } from '../model-details/onboarding-model-details.component';
/* ------------------------------------------------------------------------------------------------------------------ */

const PROBLEM_PREVIEW_LIMIT = 3;

@Component({
    selector: 'cmdb-onboarding-import-step',
    templateUrl: './onboarding-import-step.component.html',
    styleUrls: ['./onboarding-import-step.component.scss'],
    imports: [ReactiveFormsModule, CoreModule],
    changeDetection: ChangeDetectionStrategy.OnPush
})
export class OnboardingImportStepComponent implements OnInit {
    public readonly bestPractice = inject(OnboardingBestPracticeService);
    public readonly dataModel = inject(OnboardingDataModelService);
    private readonly modalService = inject(NgbModal);
    private readonly destroyRef = inject(DestroyRef);
    private readonly injector = inject(Injector);

    public readonly selectedSource = model<OnboardingImportSource | null>(null);

    /** Owned by the assistant so the file survives moving between steps. */
    public readonly dataModelFile = input.required<FormControl<File | null>>();

    /** Importing a data model or a best-practice model needs the right `base.*`. */
    public readonly canImport = input(false);

    private readonly dropzone = viewChild<string, ElementRef<HTMLElement>>('dropzone', { read: ElementRef });
    private readonly fileSummary = viewChild<ElementRef<HTMLElement>>('fileSummary');
    private readonly problemsToggle = viewChild<string, ElementRef<HTMLElement>>('problemsToggle', { read: ElementRef });

    public readonly selectedFile = toSignal(
        toObservable(this.dataModelFile).pipe(
            switchMap(control => control.valueChanges.pipe(startWith(control.value)))
        ),
        { initialValue: null }
    );

    public readonly modelName = computed(() => this.dataModel.preview()?.information?.name ?? '');

    public readonly fileSize = computed(() => {
        const file = this.selectedFile();

        return file ? formatFileSize(file.size) : '';
    });

    public readonly importOptions = computed(() =>
        IMPORT_OPTIONS.filter(option => option.id === 'empty' || this.canImport())
    );

    public readonly previewCounts = computed(() => {
        const counts = this.dataModel.preview()?.information?.counts;

        return counts ? DATA_MODEL_COUNT_LABELS.map(item => ({ ...item, value: counts[item.id] ?? 0 })) : [];
    });

    /** The backend explains a refusal in `problems`; the generic text covers an empty list. */
    public readonly previewProblems = computed(() => {
        const preview = this.dataModel.preview();

        if (!preview || preview.problems?.length) {
            return preview?.problems ?? [];
        }

        return preview.importable ? [] : ['This file cannot be imported.'];
    });

    public readonly showAllProblems = linkedSignal({ source: this.dataModel.preview, computation: () => false });

    public readonly visibleProblems = computed(() =>
        this.showAllProblems() ? this.previewProblems() : this.previewProblems().slice(0, PROBLEM_PREVIEW_LIMIT)
    );

    public readonly hasHiddenProblems = computed(() => this.previewProblems().length > PROBLEM_PREVIEW_LIMIT);

    public readonly modelCards = computed(() => (this.bestPractice.models() ?? []).map(toModelCardView));

    constructor() {
        afterRenderEffect(() => {
            if (this.dataModel.preview()) {
                this.fileSummary()?.nativeElement.scrollIntoView({ block: 'nearest' });
            }
        });
    }

    /* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    public ngOnInit(): void {
        this.loadSourceData(this.selectedSource());
    }

    /* ---------------------------------------------------- EVENTS ------------------------------------------------------ */

    public onSourceSelected(source: OnboardingImportSource): void {
        this.selectedSource.set(source);
        this.loadSourceData(source);
    }


    public onModelSelected(modelId: string): void {
        this.bestPractice.selectModel(modelId);
    }


    public onRetryModels(): void {
        this.bestPractice.loadModels();
    }


    public onToggleProblems(): void {
        this.showAllProblems.update(showAll => !showAll);
        afterNextRender(() => {
            this.problemsToggle()?.nativeElement.scrollIntoView({ block: 'nearest' });
        }, { injector: this.injector });
    }


    public onRetryPreview(): void {
        this.dataModel.loadPreview(this.dataModelFile().value);
    }


    /** The dropzone input is gone once the file card replaces it. */
    public onFileSelected(): void {
        afterNextRender(() => this.fileSummary()?.nativeElement.focus(), { injector: this.injector });
    }


    /** The remove button disappears with the file card, so focus moves to the dropzone that replaces it. */
    public onRemoveFile(): void {
        this.dataModelFile().setValue(null);
        afterNextRender(() => {
            this.dropzone()?.nativeElement.querySelector<HTMLInputElement>('input[type="file"]')?.focus();
        }, { injector: this.injector });
    }


    public onViewDetails(card: BestPracticeModelCard): void {
        this.bestPractice.loadDetails(card.model_id).pipe(
            takeUntilDestroyed(this.destroyRef)
        ).subscribe(details => this.openDetails(details));
    }

    /* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    private loadSourceData(source: OnboardingImportSource | null): void {
        if (source === 'best-practice') {
            this.bestPractice.loadModels();
        }

        if (source === 'data-model') {
            this.dataModel.loadUploadLimit();
        }
    }


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
