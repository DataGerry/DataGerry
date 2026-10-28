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


import { computed, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { OnboardingLicenseService } from '../../services/onboarding-license.service';
import { OnboardingBestPracticeService } from '../../services/onboarding-best-practice.service';
import { OnboardingDataModelService } from '../../services/onboarding-data-model.service';
import { BestPracticeModelCard } from '../../models/onboarding-best-practice.model';
import { SetupProgressLine } from '../../models/onboarding-assistant.model';
import { OnboardingSetupStepComponent } from './onboarding-setup-step.component';
/* ------------------------------------------------------------------------------------------------------------------ */

const MODEL: BestPracticeModelCard = {
    model_id: 'it_infrastructure',
    title: 'IT Infrastructure',
    badge: 'Complete CMDB',
    summary: 'Every asset class in one connected model.',
    counts: { categories: 5, types: 10, fields: 23, relations: 3 },
    category_labels: [],
    required_features: [],
    missing_features: [],
    applicable: true
};

describe('OnboardingSetupStepComponent', () => {
    let fixture: ComponentFixture<OnboardingSetupStepComponent>;
    let component: OnboardingSetupStepComponent;
    const license = signal<unknown>(null);
    const selectedModel = signal<BestPracticeModelCard | null>(null);

    const rowValue = (id: string) => component.rows().find(row => row.id === id);

    beforeEach(async () => {
        license.set(null);
        selectedModel.set(null);

        await TestBed.configureTestingModule({
            imports: [OnboardingSetupStepComponent],
            providers: [
                {
                    provide: OnboardingLicenseService,
                    useValue: { license, isActive: computed(() => !!license()), tierLabel: signal('Business') }
                },
                { provide: OnboardingBestPracticeService, useValue: { selectedModel } },
                { provide: OnboardingDataModelService, useValue: { preview: signal(null) } }
            ]
        }).compileComponents();

        fixture = TestBed.createComponent(OnboardingSetupStepComponent);
        component = fixture.componentInstance;
        fixture.componentRef.setInput('isCloud', false);
        fixture.componentRef.setInput('edition', 'community');
        fixture.componentRef.setInput('availableSteps', ['welcome', 'edition', 'import', 'setup']);
    });

    it('lists no pro features for the community edition', () => {
        fixture.detectChanges();

        expect(rowValue('pro-features')?.value).toBe('None');
        expect(rowValue('pro-features')?.features).toEqual([]);
    });

    it('lists every pro feature with the IPAM views in the cloud', () => {
        fixture.componentRef.setInput('isCloud', true);
        fixture.detectChanges();

        const features = rowValue('pro-features')?.features ?? [];

        expect(features).toContain('Port Connectivity');
        expect(features).toContain('Cabling View');
        expect(features).toContain('Rack View');
        expect(fixture.nativeElement.querySelectorAll('.onboarding-review__features li').length).toBe(features.length);
    });

    it('names the chosen best-practice model with its source and type count', () => {
        selectedModel.set(MODEL);
        fixture.componentRef.setInput('importSource', 'best-practice');
        fixture.detectChanges();

        expect(rowValue('data-model')?.value).toBe('Best practice: IT Infrastructure');
        expect(rowValue('new-types')?.value).toBe('10');
    });

    it('shows a self-hosted environment with its server', () => {
        fixture.componentRef.setInput('hostName', 'dg-cmdb-01');
        fixture.detectChanges();

        expect(rowValue('environment')?.value).toBe('Self-hosted · dg-cmdb-01');
    });

    it('shows no progress until the setup starts', () => {
        fixture.detectChanges();

        expect(fixture.nativeElement.querySelector('.onboarding-progress')).toBeNull();
    });

    it('moves the bar and logs each finished line', () => {
        const running: SetupProgressLine[] = [
            { id: 'data-model', label: 'Applying', state: 'running' },
            { id: 'complete', label: 'Setup complete', state: 'pending' }
        ];
        fixture.componentRef.setInput('progress', running);
        fixture.detectChanges();

        expect(component.progressPercent()).toBe(25);
        expect(fixture.nativeElement.querySelectorAll('.onboarding-progress__line').length).toBe(1);

        fixture.componentRef.setInput('progress', running.map(line => ({ ...line, state: 'done' })));
        fixture.detectChanges();

        expect(component.progressPercent()).toBe(100);
        expect(fixture.nativeElement.querySelectorAll('.onboarding-progress__line--done').length).toBe(2);
    });

    it('marks a failed setup', () => {
        fixture.componentRef.setInput('progress', [
            { id: 'data-model', label: 'Failed', state: 'failed' },
            { id: 'complete', label: 'Setup complete', state: 'pending' }
        ]);
        fixture.detectChanges();

        expect(component.hasFailed()).toBeTrue();
        expect(fixture.nativeElement.querySelector('.onboarding-progress--failed')).not.toBeNull();
    });
});
