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


import { signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { NgbModal } from '@ng-bootstrap/ng-bootstrap';

import { OnboardingBestPracticeService } from '../../services/onboarding-best-practice.service';
import { BestPracticeModelCard, BestPracticeSelectionPreview } from '../../models/onboarding-best-practice.model';
import { OnboardingModelPickerComponent } from './onboarding-model-picker.component';
/* ------------------------------------------------------------------------------------------------------------------ */

function card(model_id: string, title: string, categories: string[], applicable = true): BestPracticeModelCard {
    return {
        model_id,
        title,
        badge: 'Badge',
        summary: `${title} summary`,
        counts: { categories: categories.length, types: 1, fields: 1, relations: 0 },
        category_labels: categories,
        required_features: [],
        missing_features: [],
        applicable
    };
}

function selectionPreview(changes: Partial<BestPracticeSelectionPreview>): BestPracticeSelectionPreview {
    return {
        model_ids: [],
        counts: { categories: 0, types: 0, fields: 0, relations: 0 },
        category_labels: [],
        required_features: [],
        missing_features: [],
        conflicts: [],
        merged: {},
        problems: [],
        reset_blockers: [],
        applicable: true,
        ...changes
    };
}

describe('OnboardingModelPickerComponent', () => {
    let fixture: ComponentFixture<OnboardingModelPickerComponent>;
    let component: OnboardingModelPickerComponent;
    let toggleModel: jasmine.Spy;
    const models = signal<BestPracticeModelCard[] | null>(null);
    const selectedModelIds = signal<string[]>([]);
    const preview = signal<BestPracticeSelectionPreview | null>(null);
    const previewFailed = signal(false);

    const element = (): HTMLElement => fixture.nativeElement;

    beforeEach(async () => {
        models.set([
            card('it_infrastructure', 'IT Infrastructure', ['Hardware', 'Network']),
            card('workplace', 'Workplace Management', ['Contact']),
            card('data_center', 'Data Center Network', ['Network'], false)
        ]);
        selectedModelIds.set([]);
        preview.set(null);
        previewFailed.set(false);
        toggleModel = jasmine.createSpy('toggleModel');
        const isSelected = (modelId: string) => selectedModelIds().includes(modelId);

        await TestBed.configureTestingModule({
            imports: [OnboardingModelPickerComponent],
            providers: [
                {
                    provide: OnboardingBestPracticeService,
                    useValue: { models, isSelected, toggleModel, preview, previewFailed, loadPreview: () => { } }
                },
                { provide: NgbModal, useValue: jasmine.createSpyObj('NgbModal', ['open']) }
            ]
        }).compileComponents();

        fixture = TestBed.createComponent(OnboardingModelPickerComponent);
        component = fixture.componentInstance;
        fixture.detectChanges();
    });

    it('lists every model with its count', () => {
        expect(element().querySelectorAll('.onboarding-model').length).toBe(3);
        expect(component.countText()).toBe('3 models');
    });

    it('filters the models by the search term and says how many are shown', () => {
        component.search.setValue('network');
        fixture.detectChanges();

        expect(component.filteredCards().map(item => item.model_id)).toEqual(['it_infrastructure', 'data_center']);
        expect(component.countText()).toBe('2 of 3 models');
    });

    it('offers to clear a search that matches nothing', () => {
        component.search.setValue('kubernetes');
        fixture.detectChanges();

        expect(element().querySelector('.onboarding-models__empty')?.textContent).toContain('“kubernetes”');

        component.onClearSearch();
        fixture.detectChanges();

        expect(element().querySelectorAll('.onboarding-model').length).toBe(3);
    });

    it('names the search field for assistive technology', () => {
        expect(element().querySelector('input[type="search"]')?.getAttribute('aria-label')).toBe('Search models');
    });

    it('disables a model the license does not cover', () => {
        const radio = element().querySelector<HTMLInputElement>('input[value="data_center"]');

        expect(radio?.disabled).toBeTrue();
        expect(element().querySelector('#model-locked-data_center')).not.toBeNull();
    });

    it('hands each toggled model to the best-practice state', () => {
        element().querySelector<HTMLInputElement>('input[value="workplace"]')?.click();
        element().querySelector<HTMLInputElement>('input[value="it_infrastructure"]')?.click();

        expect(toggleModel.calls.allArgs()).toEqual([['workplace'], ['it_infrastructure']]);
    });

    it('marks every selected model as checked', () => {
        selectedModelIds.set(['it_infrastructure', 'workplace']);
        fixture.detectChanges();

        expect(element().querySelectorAll('input[type="checkbox"]:checked').length).toBe(2);
        expect(element().querySelectorAll('.onboarding-model--selected').length).toBe(2);
    });

    it('lists why the selection cannot be applied', () => {
        selectedModelIds.set(['it_infrastructure', 'workplace']);
        preview.set(selectionPreview({
            conflicts: ['Type "company" differs between the models.'],
            reset_blockers: ['The installation holds 3 objects.'],
            applicable: false
        }));
        fixture.detectChanges();

        const problems = Array.from(element().querySelectorAll('.onboarding-models__problems li'))
            .map(item => item.textContent?.trim());

        expect(problems).toEqual(['Type "company" differs between the models.', 'The installation holds 3 objects.']);
    });

    it('shows nothing below the list for an applicable selection', () => {
        selectedModelIds.set(['workplace']);
        preview.set(selectionPreview({ applicable: true }));
        fixture.detectChanges();

        expect(element().querySelector('.onboarding-models__selection app-warning-alert')).toBeNull();
    });

    it('says so when no models are available', () => {
        models.set([]);
        fixture.detectChanges();

        expect(element().querySelector('.onboarding-models')).toBeNull();
        expect(element().textContent).toContain('No best practice models are available.');
    });
});
