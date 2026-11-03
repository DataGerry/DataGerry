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

import { CurrentLicense, LicenseFeature } from '../../../../settings/license-management/models/license.model';
import { OnboardingLicenseService } from '../../services/onboarding-license.service';
import { OnboardingPlanStepComponent } from './onboarding-plan-step.component';
/* ------------------------------------------------------------------------------------------------------------------ */

function plan(is_active: boolean, features: LicenseFeature[]): CurrentLicense {
    return {
        is_active,
        status: null,
        entitlement: {
            hmac: '',
            startDate: 0,
            endDate: 0,
            subId: '',
            licenseId: '',
            operationUsage: 0,
            duration: 0,
            type: 'business',
            features
        }
    };
}

describe('OnboardingPlanStepComponent', () => {
    let fixture: ComponentFixture<OnboardingPlanStepComponent>;
    let loadCurrentPlan: jasmine.Spy;
    const license = signal<CurrentLicense | null>(null);
    const isLoadingLicense = signal(false);

    const element = (): HTMLElement => fixture.nativeElement;

    beforeEach(async () => {
        license.set(null);
        isLoadingLicense.set(false);
        loadCurrentPlan = jasmine.createSpy('loadCurrentPlan');

        await TestBed.configureTestingModule({
            imports: [OnboardingPlanStepComponent],
            providers: [
                {
                    provide: OnboardingLicenseService,
                    useValue: { license, isLoadingLicense, planLabel: signal('Medium plan'), loadCurrentPlan }
                }
            ]
        }).compileComponents();

        fixture = TestBed.createComponent(OnboardingPlanStepComponent);
    });

    it('loads the plan when shown and shows nothing while it loads', () => {
        isLoadingLicense.set(true);
        fixture.detectChanges();

        expect(loadCurrentPlan).toHaveBeenCalled();
        expect(element().querySelector('.license-card')).toBeNull();
        expect(element().querySelector('app-warning-alert')).toBeNull();
    });

    it('says the plan is unavailable once loading ends without one', () => {
        fixture.detectChanges();

        expect(element().querySelector('.license-card')).toBeNull();
        expect(element().querySelector('app-warning-alert')?.textContent).toContain('not available');
    });

    it('shows the plan with its features in a fixed order', () => {
        license.set(plan(true, [LicenseFeature.Isms, LicenseFeature.RestApi]));
        fixture.detectChanges();

        const features = Array.from(element().querySelectorAll('.plan-features li')).map(item => item.textContent?.trim());

        expect(element().querySelector('.license-card__title')?.textContent).toContain('Medium plan');
        expect(element().querySelector('.license-card__status')?.textContent).toContain('Active');
        expect(features).toEqual(['REST API', 'ISMS']);
    });

    it('marks an inactive plan', () => {
        license.set(plan(false, []));
        fixture.detectChanges();

        expect(element().querySelector('.license-card__status--inactive')?.textContent).toContain('Inactive');
        expect(element().querySelector('.plan-features')).toBeNull();
    });
});
