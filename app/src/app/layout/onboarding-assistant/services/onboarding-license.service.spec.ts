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

import { HttpErrorResponse } from '@angular/common/http';
import { TestBed } from '@angular/core/testing';
import { of, throwError } from 'rxjs';

import { FileSaverService } from 'ngx-filesaver';

import { LoaderService } from '../../../core/services/loader.service';
import { ToastService } from '../../toast/toast.service';
import { LicenseService } from '../../../settings/license-management/services/license.service';
import { PremiumFeatureService } from '../../../settings/license-management/premium-feature/premium-feature.service';
import { CurrentLicense, LicenseTier } from '../../../settings/license-management/models/license.model';
import {
    ActivationPhase,
    DAY_IN_MS,
    EMPTY_LICENSE_FILE_MESSAGE,
    LICENSE_IMPORT_FAILED_MESSAGE
} from '../models/onboarding-license.model';
import { OnboardingLicenseService } from './onboarding-license.service';
/* ------------------------------------------------------------------------------------------------------------------ */

function currentLicense(is_active = true): CurrentLicense {
    return {
        is_active,
        status: null,
        entitlement: {
            hmac: '',
            startDate: 0,
            endDate: 0,
            subId: 'sub',
            licenseId: 'lic-1234',
            operationUsage: 0,
            duration: 0,
            type: LicenseTier.Business,
            features: []
        }
    };
}

describe('OnboardingLicenseService', () => {
    let service: OnboardingLicenseService;
    let licenseService: jasmine.SpyObj<LicenseService>;
    let premiumFeatures: jasmine.SpyObj<PremiumFeatureService>;
    let loader: jasmine.SpyObj<LoaderService>;
    let toast: jasmine.SpyObj<ToastService>;

    const licenseFile = (content: string) => new File([content], 'license.txt');

    /** `File.text()` cannot be flushed by fakeAsync. */
    async function whenImported(): Promise<void> {
        while (service.isImporting()) {
            await new Promise(resolve => setTimeout(resolve));
        }
    }

    beforeEach(() => {
        licenseService = jasmine.createSpyObj('LicenseService',
            ['getCurrentLicense', 'generateActivationKey', 'importLicense']);
        premiumFeatures = jasmine.createSpyObj('PremiumFeatureService', ['refresh']);
        loader = jasmine.createSpyObj('LoaderService', ['show', 'hide']);
        toast = jasmine.createSpyObj('ToastService', ['success', 'error']);

        premiumFeatures.refresh.and.returnValue(of(null));

        TestBed.configureTestingModule({
            providers: [
                OnboardingLicenseService,
                { provide: LicenseService, useValue: licenseService },
                { provide: PremiumFeatureService, useValue: premiumFeatures },
                { provide: LoaderService, useValue: loader },
                { provide: ToastService, useValue: toast },
                { provide: FileSaverService, useValue: jasmine.createSpyObj('FileSaverService', ['save']) }
            ]
        });

        service = TestBed.inject(OnboardingLicenseService);
    });

    it('picks up an active license only once', () => {
        licenseService.getCurrentLicense.and.returnValue(of(currentLicense()));

        service.loadCurrentLicense();
        service.loadCurrentLicense();

        expect(licenseService.getCurrentLicense).toHaveBeenCalledTimes(1);
        expect(service.status()).toBe('active');
        expect(service.tierLabel()).toBe('Medium');
    });

    it('checks the current license again after a failed check', () => {
        licenseService.getCurrentLicense.and.returnValue(throwError(() => new Error('offline')));

        service.loadCurrentLicense();
        service.loadCurrentLicense();

        expect(licenseService.getCurrentLicense).toHaveBeenCalledTimes(2);
        expect(loader.hide).toHaveBeenCalledTimes(loader.show.calls.count());
    });

    it('keeps the cloud plan even when it is not active', () => {
        licenseService.getCurrentLicense.and.returnValue(of(currentLicense(false)));

        service.loadCurrentPlan();

        expect(service.license()?.entitlement.licenseId).toBe('lic-1234');
        expect(service.planLabel()).toBe('Subscription: Medium');
    });

    it('leaves a failed plan load to the plan step and tries again on the next load', () => {
        licenseService.getCurrentLicense.and.returnValue(throwError(() => new HttpErrorResponse({ status: 404 })));

        service.loadCurrentPlan();
        service.loadCurrentPlan();

        expect(toast.error).not.toHaveBeenCalled();
        expect(licenseService.getCurrentLicense).toHaveBeenCalledTimes(2);
        expect(service.isLoadingLicense()).toBeFalse();
    });

    it('names the cloud plan by its size', () => {
        const license = currentLicense();
        license.entitlement.type = 'basic';
        licenseService.getCurrentLicense.and.returnValue(of(license));

        service.loadCurrentPlan();

        expect(service.planLabel()).toBe('Subscription: Small');
    });

    it('names a trial by its scope and counts its days left', () => {
        const license = currentLicense();
        license.entitlement.type = 'trial';
        license.entitlement.endDate = Date.now() + 14 * DAY_IN_MS - 1000;
        licenseService.getCurrentLicense.and.returnValue(of(license));

        service.loadCurrentPlan();

        expect(service.isTrial()).toBeTrue();
        expect(service.planLabel()).toBe('Trial · Corporate');
        expect(service.trialDaysLeftLabel()).toBe('14 days left');
    });

    it('marks a trial past its end date as ended', () => {
        const license = currentLicense(false);
        license.entitlement.type = 'trial';
        license.entitlement.endDate = Date.now() - DAY_IN_MS;
        licenseService.getCurrentLicense.and.returnValue(of(license));

        service.loadCurrentPlan();

        expect(service.trialDaysLeft()).toBe(0);
        expect(service.trialDaysLeftLabel()).toBe('ended');
    });

    it('names an unknown plan type as the cloud plan', () => {
        const license = currentLicense();
        license.entitlement.type = 'starter';
        licenseService.getCurrentLicense.and.returnValue(of(license));

        service.loadCurrentPlan();

        expect(service.planLabel()).toBe('Cloud plan');
    });

    it('stays on the request once it is created so it can be downloaded, and moves on when asked', () => {
        licenseService.generateActivationKey.and.returnValue(of('  request-blob  '));

        service.createActivationRequest();

        expect(service.activationRequest()?.content).toBe('request-blob');
        expect(service.phase()).toBe(ActivationPhase.Request);

        service.continueWithExistingRequest();

        expect(service.phase()).toBe(ActivationPhase.Portal);
    });

    it('stays on the request when the backend returns an empty key', () => {
        licenseService.generateActivationKey.and.returnValue(of(''));

        service.createActivationRequest();

        expect(service.activationRequest()).toBeNull();
        expect(service.phase()).toBe(ActivationPhase.Request);
        expect(toast.error).toHaveBeenCalled();
    });

    it('activates an imported license and refreshes the entitlements', async () => {
        licenseService.importLicense.and.returnValue(of(currentLicense()));
        service.skip();

        service.importLicense(licenseFile(' blob '));
        await whenImported();

        expect(licenseService.importLicense).toHaveBeenCalledWith('blob');
        expect(service.status()).toBe('active');
        expect(premiumFeatures.refresh).toHaveBeenCalled();
        expect(loader.hide).toHaveBeenCalledTimes(loader.show.calls.count());
    });

    it('refuses an empty license file without calling the backend', async () => {
        service.importLicense(licenseFile('   '));
        await whenImported();

        expect(licenseService.importLicense).not.toHaveBeenCalled();
        expect(service.importError()).toBe(EMPTY_LICENSE_FILE_MESSAGE);
    });

    it('shows why the backend refused the license', async () => {
        licenseService.importLicense.and.returnValue(throwError(() =>
            new HttpErrorResponse({ status: 400, error: { message: 'The license belongs to another server.' } })));

        service.importLicense(licenseFile('blob'));
        await whenImported();

        expect(service.importError()).toBe('The license belongs to another server.');
    });

    it('keeps any other import failure generic', async () => {
        licenseService.importLicense.and.returnValue(throwError(() =>
            new HttpErrorResponse({ status: 500, error: { message: 'Traceback (most recent call last)' } })));

        service.importLicense(licenseFile('blob'));
        await whenImported();

        expect(service.importError()).toBe(LICENSE_IMPORT_FAILED_MESSAGE);
    });

    it('treats an inactive imported license as a failed import', async () => {
        licenseService.importLicense.and.returnValue(of(currentLicense(false)));

        service.importLicense(licenseFile('blob'));
        await whenImported();

        expect(service.isActive()).toBeFalse();
        expect(service.importError()).toBe(LICENSE_IMPORT_FAILED_MESSAGE);
    });

    it('cannot skip an active license', () => {
        licenseService.getCurrentLicense.and.returnValue(of(currentLicense()));
        service.loadCurrentLicense();

        service.skip();

        expect(service.status()).toBe('active');
    });
});
