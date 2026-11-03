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

import { TestBed } from '@angular/core/testing';
import { Subject, of, throwError } from 'rxjs';

import { LoaderService } from '../../../core/services/loader.service';
import { ImportService } from '../../../modules/import/services/import.service';
import { SystemService } from '../../../settings/system/system.service';
import { ConfigurationImportPreview } from '../../../core/models/configuration-transfer.model';
import { OnboardingDataModelService } from './onboarding-data-model.service';
/* ------------------------------------------------------------------------------------------------------------------ */

function importPreview(importable = true): ConfigurationImportPreview {
    return { information: null, reset_blockers: [], problems: [], importable };
}

describe('OnboardingDataModelService', () => {
    let service: OnboardingDataModelService;
    let importService: jasmine.SpyObj<ImportService>;
    let systemService: jasmine.SpyObj<SystemService>;
    let loader: jasmine.SpyObj<LoaderService>;

    const file = (name = 'model.json') => new File(['{}'], name);

    beforeEach(() => {
        importService = jasmine.createSpyObj('ImportService', ['previewDataModel']);
        systemService = jasmine.createSpyObj('SystemService', ['getLimits']);
        loader = jasmine.createSpyObj('LoaderService', ['show', 'hide']);

        TestBed.configureTestingModule({
            providers: [
                OnboardingDataModelService,
                { provide: ImportService, useValue: importService },
                { provide: SystemService, useValue: systemService },
                { provide: LoaderService, useValue: loader }
            ]
        });

        service = TestBed.inject(OnboardingDataModelService);
    });

    it('marks an importable file', () => {
        importService.previewDataModel.and.returnValue(of(importPreview()));

        service.loadPreview(file());

        expect(service.isImportable()).toBeTrue();
        expect(service.previewFailed()).toBeFalse();
    });

    it('drops a preview still running for an earlier file', () => {
        const earlier = new Subject<ConfigurationImportPreview>();
        importService.previewDataModel.and.returnValues(earlier, of(importPreview(false)));

        service.loadPreview(file('first.json'));
        service.loadPreview(file('second.json'));
        earlier.next(importPreview());

        expect(service.isImportable()).toBeFalse();
        expect(earlier.observed).toBeFalse();
        expect(loader.hide).toHaveBeenCalledTimes(loader.show.calls.count());
    });

    it('clears the preview when the file is removed', () => {
        importService.previewDataModel.and.returnValue(of(importPreview()));
        service.loadPreview(file());

        service.loadPreview(null);

        expect(service.preview()).toBeNull();
        expect(importService.previewDataModel).toHaveBeenCalledTimes(1);
    });

    it('flags a preview that could not be loaded', () => {
        importService.previewDataModel.and.returnValue(throwError(() => new Error('offline')));

        service.loadPreview(file());

        expect(service.previewFailed()).toBeTrue();
        expect(service.isImportable()).toBeFalse();
    });

    it('requests the upload limit only once', () => {
        systemService.getLimits.and.returnValue(of({ max_request_size: 20, max_upload_size: 10 }));

        service.loadUploadLimit();
        service.loadUploadLimit();

        expect(systemService.getLimits).toHaveBeenCalledTimes(1);
        expect(service.maxUploadSize()).toBe(10);
    });

    it('requests the upload limit again after a failure', () => {
        systemService.getLimits.and.returnValue(throwError(() => new Error('offline')));

        service.loadUploadLimit();
        service.loadUploadLimit();

        expect(systemService.getLimits).toHaveBeenCalledTimes(2);
        expect(service.maxUploadSize()).toBeNull();
    });
});
