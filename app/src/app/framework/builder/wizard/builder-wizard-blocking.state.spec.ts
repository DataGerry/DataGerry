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
* along with this program. If not, see <https://www.gnu.org/licenses/>.
*/
import { fakeAsync, tick } from '@angular/core/testing';

import { ValidationService } from '../services/validation.service';
import { BuilderWizardBlockingState } from './builder-wizard-blocking.state';

/**
 * The gate both builder wizards read before letting the user leave the content step or save.
 * It mirrors the validation service, one change detection turn late.
 */
describe('BuilderWizardBlockingState', () => {
    let validationService: ValidationService;
    let blocking: BuilderWizardBlockingState;

    beforeEach(() => {
        validationService = new ValidationService();
        blocking = new BuilderWizardBlockingState(validationService);
    });

    it('starts blocked, because no section has reported fields yet', fakeAsync(() => {
        tick();

        expect(blocking.isSectionHighlighted).toBeFalse();
        expect(blocking.isFieldHighlighted).toBeFalse();
        expect(blocking.disableFields).toBeFalse();
        expect(blocking.isSectionWithoutFields).toBeFalse();
        expect(blocking.blocked).toBeTrue();
    }));

    it('clears once every section has fields and nothing is highlighted or locked', fakeAsync(() => {
        validationService.setSectionWithoutFieldState(true);
        tick();

        expect(blocking.blocked).toBeFalse();
    }));

    it('blocks on a highlighted section, a highlighted field and the duplicate-identifier lock', fakeAsync(() => {
        validationService.setSectionWithoutFieldState(true);
        tick();

        validationService.setSectionHighlightState(true);
        tick();
        expect(blocking.blocked).toBeTrue();

        validationService.setSectionHighlightState(false);
        validationService.setFieldHighlightState(true);
        tick();
        expect(blocking.blocked).toBeTrue();

        validationService.setFieldHighlightState(false);
        validationService.setDisableFields(true);
        tick();
        expect(blocking.blocked).toBeTrue();

        validationService.setDisableFields(false);
        tick();
        expect(blocking.blocked).toBeFalse();
    }));

    it('defers its writes, so a state pushed mid change detection is not read back in the same turn', () => {
        validationService.setSectionHighlightState(true);

        expect(blocking.isSectionHighlighted).toBeFalse();
    });

    it('stops following the service once destroyed', fakeAsync(() => {
        blocking.destroy();

        validationService.setSectionHighlightState(true);
        tick();

        expect(blocking.isSectionHighlighted).toBeFalse();
    }));
});
