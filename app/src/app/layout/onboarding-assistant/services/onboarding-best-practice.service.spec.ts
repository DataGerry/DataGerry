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
import { TestBed } from '@angular/core/testing';
import { of } from 'rxjs';

import { LoaderService } from '../../../core/services/loader.service';
import { ToastService } from '../../toast/toast.service';
import { OnboardingBestPracticeService } from './onboarding-best-practice.service';
import { OnboardingLicenseService } from './onboarding-license.service';
import { OnboardingWorkspaceService } from './onboarding-workspace.service';
import { BestPracticeModelCard } from '../models/onboarding-best-practice.model';
/* ------------------------------------------------------------------------------------------------------------------ */

function card(model_id: string, applicable = true): BestPracticeModelCard {
    return {
        model_id,
        title: model_id,
        badge: '',
        summary: '',
        counts: { categories: 1, types: 1, fields: 1, relations: 0 },
        category_labels: [],
        required_features: [],
        missing_features: [],
        applicable
    };
}

describe('OnboardingBestPracticeService', () => {
    let service: OnboardingBestPracticeService;
    let workspace: jasmine.SpyObj<OnboardingWorkspaceService>;
    const license = signal<unknown>(null);

    beforeEach(() => {
        license.set(null);
        workspace = jasmine.createSpyObj('OnboardingWorkspaceService', ['getBestPracticeModels']);

        workspace.getBestPracticeModels.and.returnValue(of([card('contacts'), card('it_infrastructure'), card('ipam', false)]));

        TestBed.configureTestingModule({
            providers: [
                OnboardingBestPracticeService,
                { provide: OnboardingWorkspaceService, useValue: workspace },
                { provide: OnboardingLicenseService, useValue: { license } },
                { provide: LoaderService, useValue: jasmine.createSpyObj('LoaderService', ['show', 'hide']) },
                { provide: ToastService, useValue: jasmine.createSpyObj('ToastService', ['error']) }
            ]
        });

        service = TestBed.inject(OnboardingBestPracticeService);
        service.loadModels();
    });

    it('keeps the selection in card order whatever order it was picked in', () => {
        service.toggleModel('it_infrastructure');
        service.toggleModel('contacts');

        expect(service.selectedModels().map(model => model.model_id)).toEqual(['contacts', 'it_infrastructure']);
        expect(service.isSelectionApplicable()).toBeTrue();
    });

    it('cannot apply once the last model is deselected', () => {
        service.toggleModel('contacts');
        service.toggleModel('contacts');

        expect(service.isSelectionApplicable()).toBeFalse();
    });

    it('ignores a model the license does not cover', () => {
        service.toggleModel('ipam');

        expect(service.selectedModelIds()).toEqual([]);
        expect(service.isSelectionApplicable()).toBeFalse();
    });

    it('keeps only the models still applicable when the cards reload for another license', () => {
        service.toggleModel('contacts');
        service.toggleModel('it_infrastructure');

        workspace.getBestPracticeModels.and.returnValue(of([card('contacts'), card('it_infrastructure', false)]));
        license.set({ tier: 'business' });
        service.loadModels();

        expect(service.selectedModelIds()).toEqual(['contacts']);
    });
});
