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
import { TestBed, fakeAsync, tick } from '@angular/core/testing';
import { Router } from '@angular/router';
import { of, throwError } from 'rxjs';

import { NgbActiveModal, NgbModal } from '@ng-bootstrap/ng-bootstrap';

import { environment } from 'src/environments/environment';
import { LoaderService } from '../../core/services/loader.service';
import { SystemService } from '../../settings/system/system.service';
import { ImportService } from '../../modules/import/services/import.service';
import { ToastService } from '../toast/toast.service';
import { SidebarService } from '../services/sidebar.service';
import { UserSettingsDBService } from '../../management/user-settings/services/user-settings-db.service';
import { PremiumFeatureService } from '../../settings/license-management/premium-feature/premium-feature.service';
import { OnboardingLicenseService } from './services/onboarding-license.service';
import { OnboardingWorkspaceService } from './services/onboarding-workspace.service';
import { OnboardingBestPracticeService } from './services/onboarding-best-practice.service';
import { OnboardingDataModelService } from './services/onboarding-data-model.service';
import { OnboardingAssistantComponent } from './onboarding-assistant.component';
/* ------------------------------------------------------------------------------------------------------------------ */

describe('OnboardingAssistantComponent setup', () => {
    let component: OnboardingAssistantComponent;
    let workspace: jasmine.SpyObj<OnboardingWorkspaceService>;
    let toast: jasmine.SpyObj<ToastService>;
    let router: jasmine.SpyObj<Router>;
    const selectedModels = signal<{ model_id: string; title: string }[]>([]);
    const isSelectionApplicable = signal(false);

    beforeEach(() => {
        workspace = jasmine.createSpyObj('OnboardingWorkspaceService', ['recordDecision', 'applyBestPracticeModels']);
        toast = jasmine.createSpyObj('ToastService', ['success', 'error']);
        router = jasmine.createSpyObj('Router', ['navigate']);
        selectedModels.set([]);
        isSelectionApplicable.set(false);

        TestBed.configureTestingModule({
            imports: [OnboardingAssistantComponent],
            providers: [
                { provide: OnboardingWorkspaceService, useValue: workspace },
                { provide: ToastService, useValue: toast },
                { provide: Router, useValue: router },
                { provide: LoaderService, useValue: { isLoading$: of(false), show: () => { }, hide: () => { } } },
                { provide: SystemService, useValue: {} },
                { provide: ImportService, useValue: {} },
                { provide: SidebarService, useValue: jasmine.createSpyObj('SidebarService', ['loadCategoryTree']) },
                { provide: UserSettingsDBService, useValue: jasmine.createSpyObj('UserSettingsDBService', ['syncSettings']) },
                { provide: PremiumFeatureService, useValue: {} },
                { provide: NgbModal, useValue: {} },
                { provide: NgbActiveModal, useValue: jasmine.createSpyObj('NgbActiveModal', ['close', 'dismiss']) }
            ]
        });

        TestBed.overrideComponent(OnboardingAssistantComponent, {
            set: {
                providers: [
                    {
                        provide: OnboardingLicenseService,
                        useValue: {
                            isActive: signal(false),
                            status: signal('none'),
                            isTrial: signal(false),
                            trialDaysLeftLabel: signal(''),
                            planLabel: signal('Medium plan')
                        }
                    },
                    { provide: OnboardingBestPracticeService, useValue: { selectedModels, isSelectionApplicable } },
                    { provide: OnboardingDataModelService, useValue: { isImportable: signal(false) } }
                ]
            }
        });

        component = TestBed.createComponent(OnboardingAssistantComponent).componentInstance;
        component.currentStepIndex.set(component.stepIds().indexOf('setup'));
    });

    it('shows the running line, then both lines done, then completes', fakeAsync(() => {
        workspace.recordDecision.and.returnValue(of(undefined));

        component.onNext();

        expect(component.setupProgress().map(line => line.state)).toEqual(['done', 'done']);
        expect(component.isImporting()).toBeTrue();
        expect(component.isImportComplete()).toBeFalse();

        tick(900);

        expect(component.isImporting()).toBeFalse();
        expect(component.isImportComplete()).toBeTrue();
    }));

    it('marks the line failed and allows a retry when the request fails', fakeAsync(() => {
        workspace.recordDecision.and.returnValue(throwError(() => new Error('offline')));

        component.onNext();
        tick(900);

        expect(component.setupProgress()[0]).toEqual(jasmine.objectContaining({ state: 'failed' }));
        expect(component.isImporting()).toBeFalse();
        expect(component.isImportComplete()).toBeFalse();
        expect(toast.error).toHaveBeenCalledWith('The empty data model could not be set up.');
    }));

    it('still completes when the navigation after an applied model fails', fakeAsync(() => {
        selectedModels.set([{ model_id: 'it_infrastructure', title: 'IT Infrastructure' }]);
        component.selectedImportSource.set('best-practice');
        workspace.applyBestPracticeModels.and.returnValue(of(undefined));
        router.navigate.and.returnValue(Promise.reject(new Error('navigation failed')));

        component.onNext();
        tick(900);

        expect(component.isImportComplete()).toBeTrue();
        expect(toast.success).toHaveBeenCalledWith('The IT Infrastructure model was applied.');
        expect(toast.error).not.toHaveBeenCalled();
    }));

    it('applies every selected model in one request', fakeAsync(() => {
        selectedModels.set([
            { model_id: 'contacts', title: 'Contacts' },
            { model_id: 'it_infrastructure', title: 'IT Infrastructure' }
        ]);
        component.selectedImportSource.set('best-practice');
        workspace.applyBestPracticeModels.and.returnValue(of(undefined));
        router.navigate.and.returnValue(Promise.resolve(true));

        component.onNext();
        tick(900);

        expect(workspace.applyBestPracticeModels).toHaveBeenCalledOnceWith(['contacts', 'it_infrastructure']);
        expect(toast.success).toHaveBeenCalledWith('The Contacts and IT Infrastructure models were applied.');
    }));

    it('lets the import step continue only once the preview allows the selection', () => {
        component.canImport.set(true);
        component.selectedImportSource.set('best-practice');
        component.currentStepIndex.set(component.stepIds().indexOf('import'));

        expect(component.isNextDisabled()).toBeTrue();

        isSelectionApplicable.set(true);

        expect(component.isNextDisabled()).toBeFalse();
    });

    it('clears an earlier progress when the user goes back', fakeAsync(() => {
        workspace.recordDecision.and.returnValue(throwError(() => new Error('offline')));

        component.onNext();
        tick(900);
        component.onSecondaryAction();

        expect(component.setupProgress()).toEqual([]);
    }));

    it('runs only one setup at a time', fakeAsync(() => {
        workspace.recordDecision.and.returnValue(of(undefined));

        component.onNext();
        component.onNext();
        tick(900);

        expect(workspace.recordDecision).toHaveBeenCalledTimes(1);
    }));

    it('shows the plan step only in the cloud', () => {
        const originalCloudMode = environment.cloudMode;
        environment.cloudMode = true;

        try {
            const cloud = TestBed.createComponent(OnboardingAssistantComponent).componentInstance;

            expect(cloud.stepIds()).toEqual(['welcome', 'plan', 'import', 'setup']);
            expect(cloud.steps()[1].description).toBe('Medium plan');
            expect(component.stepIds()).not.toContain('plan');
        } finally {
            environment.cloudMode = originalCloudMode;
        }
    });
});
