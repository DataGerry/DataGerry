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
    afterRenderEffect,
    computed,
    inject,
    input,
    viewChild
} from '@angular/core';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { takeUntilDestroyed, toSignal } from '@angular/core/rxjs-interop';

import { NgbModal } from '@ng-bootstrap/ng-bootstrap';

import { CoreModule } from '../../../../core/core.module';
import { OnboardingBestPracticeService } from '../../services/onboarding-best-practice.service';
import {
    BestPracticeModelCard,
    BestPracticeModelDetails,
    MODEL_DETAILS_TITLE_ID
} from '../../models/onboarding-best-practice.model';
import { matchesModelSearch, toModelCardView } from '../../utils/onboarding-best-practice.util';
import { OnboardingModelDetailsComponent } from '../model-details/onboarding-model-details.component';
/* ------------------------------------------------------------------------------------------------------------------ */

/** The loaded best-practice models with search; the selection lives in `OnboardingBestPracticeService`. */
@Component({
    selector: 'cmdb-onboarding-model-picker',
    templateUrl: './onboarding-model-picker.component.html',
    styleUrls: ['./onboarding-model-picker.component.scss'],
    imports: [ReactiveFormsModule, CoreModule],
    changeDetection: ChangeDetectionStrategy.OnPush
})
export class OnboardingModelPickerComponent {
    public readonly bestPractice = inject(OnboardingBestPracticeService);
    private readonly modalService = inject(NgbModal);
    private readonly destroyRef = inject(DestroyRef);

    /** Scrolls the list into view once it renders, after the user picked best practice. */
    public readonly reveal = input(false);

    private readonly section = viewChild<ElementRef<HTMLElement>>('section');

    public readonly search = new FormControl('', { nonNullable: true });
    private readonly searchTerm = toSignal(this.search.valueChanges, { initialValue: '' });

    public readonly cards = computed(() => (this.bestPractice.models() ?? []).map(toModelCardView));

    public readonly filteredCards = computed(() => {
        const term = this.searchTerm();
        return this.cards().filter(card => matchesModelSearch(card, term));
    });

    public readonly countText = computed(() => {
        const total = this.cards().length;
        const shown = this.filteredCards().length;
        const noun = total === 1 ? 'model' : 'models';

        return shown === total ? `${total} ${noun}` : `${shown} of ${total} ${noun}`;
    });

    public readonly searchQuery = computed(() => this.searchTerm().trim());

    private isRevealed = false;

    constructor() {
        afterRenderEffect(() => {
            const section = this.section()?.nativeElement;

            if (section && this.reveal() && !this.isRevealed) {
                this.isRevealed = true;
                section.scrollIntoView({ block: 'nearest' });
            }
        });
    }

    /* ---------------------------------------------------- EVENTS ------------------------------------------------------ */

    public onModelSelected(modelId: string): void {
        this.bestPractice.selectModel(modelId);
    }


    public onClearSearch(): void {
        this.search.setValue('');
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
