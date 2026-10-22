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

import { ChangeDetectionStrategy, Component, ElementRef, afterNextRender, input, viewChild } from '@angular/core';

import { SetupSummaryItem } from '../../models/onboarding-assistant.model';
import { ONBOARDING_TOUR_CHAPTERS } from '../../../onboarding-tour/models/onboarding-tour-steps';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'cmdb-onboarding-complete-step',
    templateUrl: './onboarding-complete-step.component.html',
    styleUrls: ['./onboarding-complete-step.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush
})
export class OnboardingCompleteStepComponent {
    public readonly isEmptyDataModel = input(false);
    public readonly modelTitle = input('');

    public readonly tourChapters: SetupSummaryItem[] = ONBOARDING_TOUR_CHAPTERS.map((chapter, index) => ({
        id: chapter.title,
        icon: chapter.icon,
        title: `Chapter ${index + 1}`,
        value: chapter.title,
        detail: chapter.text
    }));

    private readonly title = viewChild.required<ElementRef<HTMLElement>>('title');


    /** The footer button that had focus is gone once this step replaces the import flow. */
    constructor() {
        afterNextRender(() => this.title().nativeElement.focus());
    }
}
