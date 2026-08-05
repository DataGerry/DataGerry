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
    SubnetNetworkRangeValidatorHandle,
    SubnetNetworkRangeValidatorService
} from '../services/subnet-network-range-validator.service';
import { SubnetNetworkRangeValidatorDirective } from './subnet-network-range-validator.directive';
/* ------------------------------------------------------------------------------------------------------------------ */


describe('SubnetNetworkRangeValidatorDirective', () => {
    let directive: SubnetNetworkRangeValidatorDirective;
    let validatorService: jasmine.SpyObj<SubnetNetworkRangeValidatorService>;
    let handle: jasmine.SpyObj<SubnetNetworkRangeValidatorHandle>;

    const typeInstance = { special_type: SpecialType.SUBNET } as unknown as CmdbType;

    beforeEach(() => {
        handle = jasmine.createSpyObj<SubnetNetworkRangeValidatorHandle>('handle', ['destroy']);
        validatorService = jasmine.createSpyObj<SubnetNetworkRangeValidatorService>(
            'SubnetNetworkRangeValidatorService',
            ['attach']
        );
        validatorService.attach.and.returnValue(handle);

        TestBed.configureTestingModule({
            providers: [
                SubnetNetworkRangeValidatorDirective,
                { provide: SubnetNetworkRangeValidatorService, useValue: validatorService }
            ]
        });

        directive = TestBed.inject(SubnetNetworkRangeValidatorDirective);
    });

    function configure(objectId: number | null | undefined): UntypedFormGroup {
        const form = new UntypedFormGroup({});
        directive.form = form;
        directive.typeInstance = typeInstance;
        directive.objectId = objectId;
        return form;
    }

    it('defers attach and forwards the form, type, and excludeSubnetId', fakeAsync(() => {
        const form = configure(42);

        directive.ngOnChanges();
        expect(validatorService.attach).not.toHaveBeenCalled();

        tick(0);
        expect(validatorService.attach).toHaveBeenCalledOnceWith(form, typeInstance, { excludeSubnetId: 42 });
    }));

    it('does not attach when the form or typeInstance is missing', fakeAsync(() => {
        directive.form = undefined;
        directive.typeInstance = typeInstance;

        directive.ngOnChanges();
        tick(0);
        expect(validatorService.attach).not.toHaveBeenCalled();
    }));

    describe('objectId → excludeSubnetId normalization', () => {
        const cases: Array<[string, number | null | undefined, number | null]> = [
            ['a positive id (edit mode)', 42, 42],
            ['null (create mode)', null, null],
            ['undefined', undefined, null],
            ['zero', 0, null],
            ['a negative id', -5, null]
        ];

        for (const [label, input, expected] of cases) {
            it(`maps ${label} to excludeSubnetId ${expected}`, fakeAsync(() => {
                configure(input);
                directive.ngOnChanges();
                tick(0);
                expect(validatorService.attach.calls.mostRecent().args[2]).toEqual({ excludeSubnetId: expected });
            }));
        }
    });

    it('cancels the pending attach when destroyed before it runs', fakeAsync(() => {
        configure(null);

        directive.ngOnChanges();
        directive.ngOnDestroy();
        tick(0);

        expect(validatorService.attach).not.toHaveBeenCalled();
    }));

    it('destroys the active handle on ngOnDestroy', fakeAsync(() => {
        configure(null);

        directive.ngOnChanges();
        tick(0);
        directive.ngOnDestroy();

        expect(handle.destroy).toHaveBeenCalledTimes(1);
    }));

    it('tears down the previous handle before re-attaching on subsequent changes', fakeAsync(() => {
        configure(null);

        directive.ngOnChanges();
        tick(0);

        directive.ngOnChanges();
        expect(handle.destroy).toHaveBeenCalledTimes(1);
        tick(0);
        expect(validatorService.attach).toHaveBeenCalledTimes(2);
    }));
});
