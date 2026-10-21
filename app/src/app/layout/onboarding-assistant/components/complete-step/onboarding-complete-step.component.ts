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

import { ChangeDetectionStrategy, Component, ElementRef, afterNextRender, viewChild } from '@angular/core';

import { SetupSummaryItem } from '../../models/onboarding-assistant.model';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'cmdb-onboarding-complete-step',
    templateUrl: './onboarding-complete-step.component.html',
    styleUrls: ['./onboarding-complete-step.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush
})
export class OnboardingCompleteStepComponent {
    public readonly tourChapters: SetupSummaryItem[] = [
        {
            id: 'navigate',
            icon: 'fas fa-compass',
            title: 'Chapter 1',
            value: 'Find your way',
            detail: 'Sidebar, categories and search'
        },
        {
            id: 'create-type',
            icon: 'fas fa-object-group',
            title: 'Chapter 2',
            value: 'Create a type',
            detail: 'Sections and fields'
        },
        {
            id: 'add-object',
            icon: 'fas fa-cube',
            title: 'Chapter 3',
            value: 'Add an object',
            detail: 'From a type to a real asset'
        }
    ];

    private readonly title = viewChild.required<ElementRef<HTMLElement>>('title');


    /** The footer button that had focus is gone once this step replaces the import flow. */
    constructor() {
        afterNextRender(() => this.title().nativeElement.focus());
    }
}
