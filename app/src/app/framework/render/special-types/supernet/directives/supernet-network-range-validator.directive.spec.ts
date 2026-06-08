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
import { fakeAsync, TestBed, tick } from '@angular/core/testing';
import { UntypedFormGroup } from '@angular/forms';

import { CmdbType } from '../../../../models/cmdb-type';
import { SpecialType } from '../../../../models/special-type';
import {
    SupernetNetworkRangeValidatorHandle,
    SupernetNetworkRangeValidatorService
} from '../services/supernet-network-range-validator.service';
import { SupernetNetworkRangeValidatorDirective } from './supernet-network-range-validator.directive';
/* ------------------------------------------------------------------------------------------------------------------ */


describe('SupernetNetworkRangeValidatorDirective', () => {
    let directive: SupernetNetworkRangeValidatorDirective;
    let validatorService: jasmine.SpyObj<SupernetNetworkRangeValidatorService>;
    let handle: jasmine.SpyObj<SupernetNetworkRangeValidatorHandle>;

    const typeInstance = { special_type: SpecialType.SUPERNET } as unknown as CmdbType;

    beforeEach(() => {
        handle = jasmine.createSpyObj<SupernetNetworkRangeValidatorHandle>('handle', ['destroy']);
        validatorService = jasmine.createSpyObj<SupernetNetworkRangeValidatorService>(
            'SupernetNetworkRangeValidatorService',
            ['attach']
        );
        validatorService.attach.and.returnValue(handle);

        TestBed.configureTestingModule({
            providers: [
                SupernetNetworkRangeValidatorDirective,
                { provide: SupernetNetworkRangeValidatorService, useValue: validatorService }
            ]
        });

        directive = TestBed.inject(SupernetNetworkRangeValidatorDirective);
    });


    it('defers attach until the next tick so child controls can register first', fakeAsync(() => {
        const form = new UntypedFormGroup({});
        directive.form = form;
        directive.typeInstance = typeInstance;

        directive.ngOnChanges();
        expect(validatorService.attach).not.toHaveBeenCalled();   // not synchronous

        tick(0);
        expect(validatorService.attach).toHaveBeenCalledOnceWith(form, typeInstance);
    }));

    it('does not attach when the form or typeInstance is missing', fakeAsync(() => {
        directive.form = undefined;
        directive.typeInstance = typeInstance;

        directive.ngOnChanges();
        tick(0);
        expect(validatorService.attach).not.toHaveBeenCalled();
    }));

    it('cancels the pending attach when destroyed before it runs', fakeAsync(() => {
        directive.form = new UntypedFormGroup({});
        directive.typeInstance = typeInstance;

        directive.ngOnChanges();
        directive.ngOnDestroy();
        tick(0);

        expect(validatorService.attach).not.toHaveBeenCalled();
    }));

    it('destroys the active handle on ngOnDestroy', fakeAsync(() => {
        directive.form = new UntypedFormGroup({});
        directive.typeInstance = typeInstance;

        directive.ngOnChanges();
        tick(0);
        directive.ngOnDestroy();

        expect(handle.destroy).toHaveBeenCalledTimes(1);
    }));

    it('tears down the previous handle before re-attaching on subsequent changes', fakeAsync(() => {
        directive.form = new UntypedFormGroup({});
        directive.typeInstance = typeInstance;

        directive.ngOnChanges();
        tick(0);

        directive.ngOnChanges();
        expect(handle.destroy).toHaveBeenCalledTimes(1);   // previous handle disposed eagerly
        tick(0);
        expect(validatorService.attach).toHaveBeenCalledTimes(2);
    }));
});
