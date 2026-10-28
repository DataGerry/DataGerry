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
import { BestPracticeModelCard } from '../../models/onboarding-best-practice.model';
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

describe('OnboardingModelPickerComponent', () => {
    let fixture: ComponentFixture<OnboardingModelPickerComponent>;
    let component: OnboardingModelPickerComponent;
    let selectModel: jasmine.Spy;
    const models = signal<BestPracticeModelCard[] | null>(null);
    const selectedModelId = signal<string | null>(null);

    const element = (): HTMLElement => fixture.nativeElement;

    beforeEach(async () => {
        models.set([
            card('it_infrastructure', 'IT Infrastructure', ['Hardware', 'Network']),
            card('workplace', 'Workplace Management', ['Contact']),
            card('data_center', 'Data Center Network', ['Network'], false)
        ]);
        selectedModelId.set(null);
        selectModel = jasmine.createSpy('selectModel');

        await TestBed.configureTestingModule({
            imports: [OnboardingModelPickerComponent],
            providers: [
                { provide: OnboardingBestPracticeService, useValue: { models, selectedModelId, selectModel } },
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

    it('hands the picked model to the best-practice state', () => {
        element().querySelector<HTMLInputElement>('input[value="workplace"]')?.click();

        expect(selectModel).toHaveBeenCalledWith('workplace');
    });

    it('says so when no models are available', () => {
        models.set([]);
        fixture.detectChanges();

        expect(element().querySelector('.onboarding-models')).toBeNull();
        expect(element().textContent).toContain('No best practice models are available.');
    });
});
