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

import { AsyncPipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { toObservable, toSignal } from '@angular/core/rxjs-interop';
import { concat, of } from 'rxjs';
import { switchMap } from 'rxjs/operators';

import { NgbActiveModal } from '@ng-bootstrap/ng-bootstrap';

import { CoreModule } from '../../../../core/core.module';
import { LoaderService } from '../../../../core/services/loader.service';
import { OnboardingBestPracticeService } from '../../services/onboarding-best-practice.service';
import {
    BEST_PRACTICE_GOALS,
    BestPracticeGoalView,
    BestPracticeModelCardView,
    MODEL_GOALS_TITLE_ID
} from '../../models/onboarding-best-practice.model';
import { toFeatureList, toGoalView, toNameList } from '../../utils/onboarding-best-practice.util';
/* ------------------------------------------------------------------------------------------------------------------ */

const VISIBLE_CATEGORY_COUNT = 5;

/** Closes with the model ids of the picked goal that the license covers. */
@Component({
    selector: 'cmdb-onboarding-model-goals',
    templateUrl: './onboarding-model-goals.component.html',
    styleUrls: ['./onboarding-model-goals.component.scss'],
    imports: [AsyncPipe, ReactiveFormsModule, CoreModule],
    changeDetection: ChangeDetectionStrategy.OnPush
})
export class OnboardingModelGoalsComponent {
    public readonly activeModal = inject(NgbActiveModal);
    private readonly bestPractice = inject(OnboardingBestPracticeService);
    private readonly loaderService = inject(LoaderService);

    public readonly titleId = MODEL_GOALS_TITLE_ID;
    public readonly isLoading$ = this.loaderService.isLoading$;

    /** Set by the opener. */
    public readonly cards = signal<BestPracticeModelCardView[]>([]);

    public readonly goals = computed(() =>
        BEST_PRACTICE_GOALS.map(goal => toGoalView(goal, this.cards())).filter(goal => goal.models.length > 0)
    );

    public readonly goalControl = new FormControl(BEST_PRACTICE_GOALS[0].id, { nonNullable: true });
    private readonly goalId = toSignal(this.goalControl.valueChanges, { initialValue: this.goalControl.value });

    public readonly selectedGoal = computed<BestPracticeGoalView | undefined>(() => {
        const goals = this.goals();
        return goals.find(goal => goal.id === this.goalId()) ?? goals[0];
    });

    /** Cleared while the next goal's combination loads, so the shared count never belongs to another goal. */
    public readonly preview = toSignal(
        toObservable(computed(() => this.selectedGoal()?.applicableModelIds ?? [])).pipe(
            switchMap(modelIds => modelIds.length
                ? concat(of(null), this.bestPractice.loadSelectionPreview(modelIds))
                : of(null))
        ),
        { initialValue: null }
    );

    public readonly sharedTypeCount = computed(() => this.preview()?.merged.types?.length ?? 0);

    public readonly lockedMessage = computed(() => {
        const goal = this.selectedGoal();

        if (!goal?.lockedModels.length) {
            return '';
        }

        const locked = goal.lockedModels;
        const features = toFeatureList([...new Set(locked.flatMap(model => model.missing_features))]);
        const remaining = goal.applicableModelIds.length;

        return `${toNameList(locked.map(model => model.title))} ${locked.length === 1 ? 'needs' : 'need'} ${features}, `
            + `which your license does not include. Only the other ${this.toModelCount(remaining)} will be selected.`;
    });

    public readonly applyLabel = computed(() =>
        `Select ${this.toModelCount(this.selectedGoal()?.applicableModelIds.length ?? 0)}`
    );

    public readonly modelCountText = computed(() => {
        const goal = this.selectedGoal();

        if (!goal) {
            return '';
        }

        const total = this.toModelCount(goal.models.length);
        return goal.lockedModels.length ? `${goal.applicableModelIds.length} of ${total}` : total;
    });

    /* ---------------------------------------------------- EVENTS ------------------------------------------------------ */

    public onApply(): void {
        const goal = this.selectedGoal();

        if (goal?.applicableModelIds.length) {
            this.activeModal.close(goal.applicableModelIds);
        }
    }

    /* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    public visibleCategories(model: BestPracticeModelCardView): string[] {
        return model.category_labels.slice(0, VISIBLE_CATEGORY_COUNT);
    }


    public hiddenCategoryCount(model: BestPracticeModelCardView): number {
        return Math.max(0, model.category_labels.length - VISIBLE_CATEGORY_COUNT);
    }

    /* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    private toModelCount(count: number): string {
        return `${count} ${count === 1 ? 'model' : 'models'}`;
    }
}
