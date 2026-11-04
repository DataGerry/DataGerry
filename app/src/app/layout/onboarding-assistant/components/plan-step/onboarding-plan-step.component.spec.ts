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
    const isTrial = signal(false);
    const planSize = signal('Medium');
    const trialDaysLeft = signal<number | null>(null);
    const trialDaysLeftLabel = signal('');

    const element = (): HTMLElement => fixture.nativeElement;
    const text = (selector: string): string => element().querySelector(selector)?.textContent?.trim() ?? '';

    beforeEach(async () => {
        license.set(null);
        isLoadingLicense.set(false);
        isTrial.set(false);
        planSize.set('Medium');
        trialDaysLeft.set(null);
        trialDaysLeftLabel.set('');
        loadCurrentPlan = jasmine.createSpy('loadCurrentPlan');

        await TestBed.configureTestingModule({
            imports: [OnboardingPlanStepComponent],
            providers: [
                {
                    provide: OnboardingLicenseService,
                    useValue: {
                        license, isLoadingLicense, isTrial, planSize, trialDaysLeft, trialDaysLeftLabel, loadCurrentPlan
                    }
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
        expect(text('app-warning-alert')).toContain('not available');
    });

    it('shows a subscription with every Pro feature and locks the ones outside the plan', () => {
        license.set(plan(true, [LicenseFeature.RestApi, LicenseFeature.Ipam, LicenseFeature.Isms]));
        fixture.detectChanges();

        const titles = Array.from(element().querySelectorAll('.plan-features__title')).map(item => item.textContent?.trim());
        const locked = Array.from(element().querySelectorAll('.plan-features__item--locked .plan-features__title'))
            .map(item => item.textContent?.trim());

        expect(text('.onboarding__title')).toBe('Your subscription');
        expect(text('.license-card__title')).toBe('Subscription Medium');
        expect(text('.license-card__status')).toContain('Active');
        expect(titles).toEqual(['REST API', 'Networks', 'Document Generator', 'Automations', 'ISMS']);
        expect(locked).toEqual(['Document Generator', 'Automations']);
        expect(text('.plan-features__item--locked .plan-features__description')).toContain('from Large');
        expect(element().querySelector('.onboarding__note--warning')).toBeNull();
        expect(element().querySelector('.plan-features a, .plan-features app-button')).toBeNull();
        expect(element().querySelector('a[target="_blank"]')).toBeNull();
    });

    it('describes Networks by what it covers', () => {
        license.set(plan(true, [LicenseFeature.Ipam]));
        fixture.detectChanges();

        const networks = Array.from(element().querySelectorAll('.plan-features__item'))
            .find(item => item.textContent?.includes('Networks'));

        expect(networks?.textContent).toContain('IPAM, ports, cabling view and rack view');
    });

    it('shows a trial with every feature, its end, the note on what follows and the way to a plan', () => {
        const trial = plan(true, []);
        trial.entitlement.startDate = Date.UTC(2026, 9, 7);
        trial.entitlement.endDate = Date.UTC(2026, 10, 6);
        license.set(trial);
        isTrial.set(true);
        planSize.set('Corporate');
        trialDaysLeft.set(14);
        trialDaysLeftLabel.set('14 days left');
        fixture.detectChanges();

        expect(text('.onboarding__title')).toBe('Your trial');
        expect(text('.onboarding__lead')).toContain('During the 30-day trial');
        expect(text('.license-card__title')).toBe('Trial · Corporate scope');
        expect(element().querySelectorAll('.plan-features__item--locked').length).toBe(0);
        expect(text('.license-card__meta')).toContain('14 days left');
        expect(text('.license-card__status--trial')).toBe('Trial');
        expect(text('.onboarding__note--warning')).toContain('After the trial');
        expect(element().querySelector('a[target="_blank"]')?.getAttribute('rel')).toBe('noopener noreferrer');
    });

    it('marks an inactive plan', () => {
        license.set(plan(false, []));
        fixture.detectChanges();

        expect(text('.license-card__status--inactive')).toContain('Inactive');
    });
});
