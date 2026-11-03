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
import { FormControl } from '@angular/forms';

import { ConfigurationImportPreview } from '../../../../core/models/configuration-transfer.model';
import { OnboardingBestPracticeService } from '../../services/onboarding-best-practice.service';
import { OnboardingDataModelService } from '../../services/onboarding-data-model.service';
import { OnboardingImportStepComponent } from './onboarding-import-step.component';
/* ------------------------------------------------------------------------------------------------------------------ */

function importPreview(changes: Partial<ConfigurationImportPreview>): ConfigurationImportPreview {
    return { information: null, reset_blockers: [], problems: [], importable: true, ...changes };
}

describe('OnboardingImportStepComponent', () => {
    let fixture: ComponentFixture<OnboardingImportStepComponent>;
    let component: OnboardingImportStepComponent;
    let loadModels: jasmine.Spy;
    let loadUploadLimit: jasmine.Spy;
    const preview = signal<ConfigurationImportPreview | null>(null);

    const element = (): HTMLElement => fixture.nativeElement;
    const sourceIds = () => Array.from(element().querySelectorAll<HTMLInputElement>('input[name="import-source"]'))
        .map(input => input.value);

    beforeEach(async () => {
        preview.set(null);
        loadModels = jasmine.createSpy('loadModels');
        loadUploadLimit = jasmine.createSpy('loadUploadLimit');

        await TestBed.configureTestingModule({
            imports: [OnboardingImportStepComponent],
            providers: [
                {
                    provide: OnboardingBestPracticeService,
                    useValue: { loadModels, loadFailed: signal(false), models: signal(null) }
                },
                {
                    provide: OnboardingDataModelService,
                    useValue: {
                        preview,
                        previewFailed: signal(false),
                        isImportable: computed(() => !!preview()?.importable),
                        maxUploadSize: signal(null),
                        loadUploadLimit,
                        loadPreview: () => { }
                    }
                }
            ]
        }).compileComponents();

        fixture = TestBed.createComponent(OnboardingImportStepComponent);
        component = fixture.componentInstance;
        fixture.componentRef.setInput('dataModelFile', new FormControl<File | null>(null));
        fixture.componentRef.setInput('selectedSource', 'empty');
    });

    it('offers only the empty data model without the import right', () => {
        fixture.detectChanges();

        expect(sourceIds()).toEqual(['empty']);
    });

    it('offers every source with the import right', () => {
        fixture.componentRef.setInput('canImport', true);
        fixture.detectChanges();

        expect(sourceIds()).toEqual(['empty', 'best-practice', 'data-model']);
    });

    it('loads what the picked source needs', () => {
        fixture.componentRef.setInput('canImport', true);
        fixture.detectChanges();

        component.onSourceSelected('best-practice');
        component.onSourceSelected('data-model');

        expect(loadModels).toHaveBeenCalledTimes(1);
        expect(loadUploadLimit).toHaveBeenCalledTimes(1);
        expect(component.selectedSource()).toBe('data-model');
    });

    it('shows the selected file instead of the dropzone', () => {
        fixture.componentRef.setInput('canImport', true);
        fixture.componentRef.setInput('selectedSource', 'data-model');
        fixture.componentRef.setInput('selectedFile', new File(['{}'], 'model.json'));
        fixture.detectChanges();

        expect(element().querySelector('app-file-dropzone')).toBeNull();
        expect(element().querySelector('#data-model-file-title')?.textContent).toContain('model.json');
    });

    it('explains a refused file without problems in generic words', () => {
        preview.set(importPreview({ importable: false }));

        expect(component.previewProblems()).toEqual(['This file cannot be imported.']);
    });

    it('shows the first problems until the user asks for all of them', () => {
        preview.set(importPreview({ importable: false, problems: ['a', 'b', 'c', 'd'] }));

        expect(component.visibleProblems()).toEqual(['a', 'b', 'c']);
        expect(component.hasHiddenProblems()).toBeTrue();

        component.showAllProblems.set(true);

        expect(component.visibleProblems()).toEqual(['a', 'b', 'c', 'd']);
    });
});
