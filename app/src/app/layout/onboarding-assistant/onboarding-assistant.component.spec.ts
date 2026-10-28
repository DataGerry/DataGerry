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
    const selectedModel = signal<{ model_id: string; title: string } | null>(null);

    beforeEach(() => {
        workspace = jasmine.createSpyObj('OnboardingWorkspaceService', ['recordDecision', 'applyBestPracticeModel']);
        toast = jasmine.createSpyObj('ToastService', ['success', 'error']);
        router = jasmine.createSpyObj('Router', ['navigate']);
        selectedModel.set(null);

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
                    { provide: OnboardingLicenseService, useValue: { isActive: signal(false), status: signal('none') } },
                    { provide: OnboardingBestPracticeService, useValue: { selectedModel } },
                    { provide: OnboardingDataModelService, useValue: { isImportable: signal(false) } }
                ]
            }
        });

        component = TestBed.createComponent(OnboardingAssistantComponent).componentInstance;
        component.currentStepIndex.set(component.stepIds().indexOf('setup'));
    });

    it('shows the running line, then both lines done, then the last step', fakeAsync(() => {
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
        selectedModel.set({ model_id: 'it_infrastructure', title: 'IT Infrastructure' });
        component.selectedImportSource.set('best-practice');
        workspace.applyBestPracticeModel.and.returnValue(of(undefined));
        router.navigate.and.returnValue(Promise.reject(new Error('navigation failed')));

        component.onNext();
        tick(900);

        expect(component.isImportComplete()).toBeTrue();
        expect(toast.success).toHaveBeenCalledWith('The IT Infrastructure model was applied.');
        expect(toast.error).not.toHaveBeenCalled();
    }));

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
});
