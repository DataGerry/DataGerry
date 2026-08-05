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
import {
    UntypedFormControl,
    UntypedFormGroup,
    ValidatorFn,
    Validators
} from '@angular/forms';
import { of, throwError } from 'rxjs';

import { CmdbType } from '../../../../models/cmdb-type';
import { SpecialType } from '../../../../models/special-type';
import { SUPERNET_FIELD_NAMES } from '../models/supernet-fields';
import { SupernetValidationResponse } from '../models/supernet-validation.types';
import { SupernetIpamApiService } from './supernet-ipam-api.service';
import {
    BACKEND_VALIDATION_ERROR_KEY,
    SupernetNetworkRangeValidatorService
} from './supernet-network-range-validator.service';
/* ------------------------------------------------------------------------------------------------------------------ */


describe('SupernetNetworkRangeValidatorService', () => {
    let service: SupernetNetworkRangeValidatorService;
    let api: jasmine.SpyObj<SupernetIpamApiService>;

    /** Mirrors the private DEBOUNCE_MS in the service under test. */
    const DEBOUNCE_MS = 400;

    function buildType(specialType?: SpecialType | string | null): CmdbType {
        return { special_type: specialType } as unknown as CmdbType;
    }

    function buildForm(opts: {
        networkRange?: boolean;
        supernetType?: boolean;
        rangeValidators?: ValidatorFn[];
    } = {}): UntypedFormGroup {
        const controls: Record<string, UntypedFormControl> = {};

        if (opts.networkRange ?? true) {
            controls[SUPERNET_FIELD_NAMES.NETWORK_RANGE] = new UntypedFormControl('', opts.rangeValidators ?? []);
        }

        if (opts.supernetType ?? true) {
            controls[SUPERNET_FIELD_NAMES.SUPERNET_TYPE] = new UntypedFormControl('');
        }

        return new UntypedFormGroup(controls);
    }

    function setRange(form: UntypedFormGroup, value: unknown): void {
        form.get(SUPERNET_FIELD_NAMES.NETWORK_RANGE)!.setValue(value);
    }

    function setType(form: UntypedFormGroup, value: unknown): void {
        form.get(SUPERNET_FIELD_NAMES.SUPERNET_TYPE)!.setValue(value);
    }

    function rangeErrors(form: UntypedFormGroup): Record<string, any> | null {
        return form.get(SUPERNET_FIELD_NAMES.NETWORK_RANGE)!.errors;
    }

    function valid(): SupernetValidationResponse {
        return { valid: true, errors: [] };
    }

    beforeEach(() => {
        api = jasmine.createSpyObj<SupernetIpamApiService>('SupernetIpamApiService', ['validateSupernet']);
        api.validateSupernet.and.returnValue(of(valid()));

        TestBed.configureTestingModule({
            providers: [
                SupernetNetworkRangeValidatorService,
                { provide: SupernetIpamApiService, useValue: api }
            ]
        });

        service = TestBed.inject(SupernetNetworkRangeValidatorService);
    });


    describe('attach() gating — only an active SUPERNET form is wired', () => {
        const inertCases: Array<[string, CmdbType | undefined]> = [
            ['typeInstance is undefined', undefined],
            ['special_type is undefined (a normal object)', buildType(undefined)],
            ['special_type is null', buildType(null)],
            ['special_type is SUBNET', buildType(SpecialType.SUBNET)],
            ['special_type is VLAN', buildType(SpecialType.VLAN)],
            ['special_type has the wrong case ("supernet")', buildType('supernet')]
        ];

        for (const [label, typeInstance] of inertCases) {
            it(`never calls the backend when ${label}`, fakeAsync(() => {
                const form = buildForm();
                const handle = service.attach(form, typeInstance);

                setType(form, 'ipv4');
                setRange(form, '10.0.0.0/8');
                tick(DEBOUNCE_MS);

                expect(api.validateSupernet).not.toHaveBeenCalled();
                expect(rangeErrors(form)).toBeNull();
                expect(() => handle.destroy()).not.toThrow();
            }));
        }

        it('is inert and safe when the form is null', () => {
            const handle = service.attach(null as any, buildType(SpecialType.SUPERNET));
            expect(() => handle.destroy()).not.toThrow();
        });

        it('is inert when the dg-network-range control is missing', fakeAsync(() => {
            const form = buildForm({ networkRange: false });
            service.attach(form, buildType(SpecialType.SUPERNET));

            setType(form, 'ipv4');
            tick(DEBOUNCE_MS);

            expect(api.validateSupernet).not.toHaveBeenCalled();
        }));

        it('is inert when the dg-supernet-type control is missing', fakeAsync(() => {
            const form = buildForm({ supernetType: false });
            service.attach(form, buildType(SpecialType.SUPERNET));

            setRange(form, '10.0.0.0/8');
            tick(DEBOUNCE_MS);

            expect(api.validateSupernet).not.toHaveBeenCalled();
        }));
    });


    describe('validation flow', () => {
        it('sends { network_range, supernet_type } and clears errors when the backend says valid', fakeAsync(() => {
            const form = buildForm();
            service.attach(form, buildType(SpecialType.SUPERNET));

            setType(form, 'ipv4');
            setRange(form, '10.0.0.0/8');
            tick(DEBOUNCE_MS);

            expect(api.validateSupernet).toHaveBeenCalledTimes(1);
            expect(api.validateSupernet.calls.mostRecent().args[0]).toEqual({
                network_range: '10.0.0.0/8',
                supernet_type: 'ipv4'
            });
            expect(rangeErrors(form)).toBeNull();
        }));

        it('does not call the backend until a supernet type is selected', fakeAsync(() => {
            const form = buildForm();
            service.attach(form, buildType(SpecialType.SUPERNET));

            setRange(form, '10.0.0.0/8');
            tick(DEBOUNCE_MS);

            expect(api.validateSupernet).not.toHaveBeenCalled();
            // The empty type must not block the range — its own required validator owns that message.
            expect(rangeErrors(form)).toBeNull();
        }));

        it('does not call the backend for an empty or whitespace-only range', fakeAsync(() => {
            const form = buildForm();
            service.attach(form, buildType(SpecialType.SUPERNET));
            setType(form, 'ipv4');

            for (const value of ['', '   ']) {
                api.validateSupernet.calls.reset();
                setRange(form, value);
                tick(DEBOUNCE_MS);
                expect(api.validateSupernet).not.toHaveBeenCalled();
            }
        }));

        it('does not call the backend when the type value is not a usable string', fakeAsync(() => {
            const form = buildForm();
            service.attach(form, buildType(SpecialType.SUPERNET));

            setRange(form, '10.0.0.0/8');
            setType(form, 123 as any);
            tick(DEBOUNCE_MS);

            expect(api.validateSupernet).not.toHaveBeenCalled();
        }));

        it('trims whitespace around the range and type before sending', fakeAsync(() => {
            const form = buildForm();
            service.attach(form, buildType(SpecialType.SUPERNET));

            setType(form, '  ipv4  ');
            setRange(form, '  10.0.0.0/8  ');
            tick(DEBOUNCE_MS);

            expect(api.validateSupernet.calls.mostRecent().args[0]).toEqual({
                network_range: '10.0.0.0/8',
                supernet_type: 'ipv4'
            });
        }));

        it('re-validates when the supernet type changes', fakeAsync(() => {
            const form = buildForm();
            service.attach(form, buildType(SpecialType.SUPERNET));

            setRange(form, '10.0.0.0/8');
            setType(form, 'ipv4');
            tick(DEBOUNCE_MS);
            expect(api.validateSupernet.calls.mostRecent().args[0].supernet_type).toBe('ipv4');

            api.validateSupernet.calls.reset();
            setType(form, 'ipv6');
            tick(DEBOUNCE_MS);
            expect(api.validateSupernet).toHaveBeenCalledTimes(1);
            expect(api.validateSupernet.calls.mostRecent().args[0].supernet_type).toBe('ipv6');
        }));

        it('does not re-validate when the type is re-set to the same value (distinctUntilChanged)', fakeAsync(() => {
            const form = buildForm();
            service.attach(form, buildType(SpecialType.SUPERNET));

            setRange(form, '10.0.0.0/8');
            setType(form, 'ipv4');
            tick(DEBOUNCE_MS);

            api.validateSupernet.calls.reset();
            setType(form, 'ipv4');
            tick(DEBOUNCE_MS);
            expect(api.validateSupernet).not.toHaveBeenCalled();
        }));

        it('debounces rapid range edits and only sends the latest value (switchMap)', fakeAsync(() => {
            const form = buildForm();
            service.attach(form, buildType(SpecialType.SUPERNET));
            setType(form, 'ipv4');

            setRange(form, '10.0.0.0/8');
            tick(DEBOUNCE_MS - 200);             // first request still pending
            setRange(form, '10.0.0.0/24');       // supersedes the pending request
            tick(DEBOUNCE_MS);

            expect(api.validateSupernet).toHaveBeenCalledTimes(1);
            expect(api.validateSupernet.calls.mostRecent().args[0].network_range).toBe('10.0.0.0/24');
        }));
    });


    describe('regex gate — async validation only runs after the sync pattern passes', () => {
        const CIDR = Validators.pattern(/^\d{1,3}(\.\d{1,3}){3}\/\d{1,2}$/);

        it('skips the backend while the range fails its regex, then calls it once it passes', fakeAsync(() => {
            const form = buildForm({ rangeValidators: [CIDR] });
            service.attach(form, buildType(SpecialType.SUPERNET));
            setType(form, 'ipv4');

            setRange(form, 'not-a-cidr');
            tick(DEBOUNCE_MS);
            expect(api.validateSupernet).not.toHaveBeenCalled();
            expect(rangeErrors(form)?.pattern).toBeTruthy();

            setRange(form, '10.0.0.0/8');
            tick(DEBOUNCE_MS);
            expect(api.validateSupernet).toHaveBeenCalledTimes(1);
        }));
    });


    describe('backend error mapping', () => {
        it('maps a type/family mismatch to a backendValidation error carrying message, code and errors', fakeAsync(() => {
            api.validateSupernet.and.returnValue(of({
                valid: false,
                errors: [{
                    code: 'type_family_mismatch',
                    message: "Supernet type 'ipv6' does not match the address family 'ipv4' of 10.0.0.0/8",
                    details: { candidate: '10.0.0.0/8', supernet_type: 'ipv6', cidr_family: 'ipv4' }
                }]
            } as SupernetValidationResponse));

            const form = buildForm();
            service.attach(form, buildType(SpecialType.SUPERNET));
            setType(form, 'ipv6');
            setRange(form, '10.0.0.0/8');
            tick(DEBOUNCE_MS);

            const error = rangeErrors(form)?.[BACKEND_VALIDATION_ERROR_KEY];
            expect(error).toBeTruthy();
            expect(error.code).toBe('type_family_mismatch');
            expect(error.message).toContain('does not match the address family');
            expect(error.errors.length).toBe(1);
        }));

        it('falls back to a default message when the backend reports invalid with no error details', fakeAsync(() => {
            api.validateSupernet.and.returnValue(of({ valid: false, errors: [] } as SupernetValidationResponse));

            const form = buildForm();
            service.attach(form, buildType(SpecialType.SUPERNET));
            setType(form, 'ipv4');
            setRange(form, '10.0.0.0/8');
            tick(DEBOUNCE_MS);

            expect(rangeErrors(form)?.[BACKEND_VALIDATION_ERROR_KEY].message).toBe('Invalid supernet network range.');
        }));

        it('treats a null/empty backend response as valid', fakeAsync(() => {
            api.validateSupernet.and.returnValue(of(null as any));

            const form = buildForm();
            service.attach(form, buildType(SpecialType.SUPERNET));
            setType(form, 'ipv4');
            setRange(form, '10.0.0.0/8');
            tick(DEBOUNCE_MS);

            expect(rangeErrors(form)).toBeNull();
        }));

        it('does not block the form when the API errors out', fakeAsync(() => {
            api.validateSupernet.and.returnValue(throwError(() => new Error('network down')));

            const form = buildForm();
            service.attach(form, buildType(SpecialType.SUPERNET));
            setType(form, 'ipv4');
            setRange(form, '10.0.0.0/8');
            tick(DEBOUNCE_MS);

            expect(rangeErrors(form)).toBeNull();
        }));
    });


    describe('destroy() — full teardown', () => {
        it('removes the async validator so later edits no longer hit the backend', fakeAsync(() => {
            const form = buildForm();
            const handle = service.attach(form, buildType(SpecialType.SUPERNET));

            setType(form, 'ipv4');
            setRange(form, '10.0.0.0/8');
            tick(DEBOUNCE_MS);
            expect(api.validateSupernet).toHaveBeenCalledTimes(1);

            handle.destroy();
            api.validateSupernet.calls.reset();
            setRange(form, '192.168.0.0/16');
            tick(DEBOUNCE_MS);
            expect(api.validateSupernet).not.toHaveBeenCalled();
        }));

        it('stops re-validating on type changes after destroy', fakeAsync(() => {
            const form = buildForm();
            const handle = service.attach(form, buildType(SpecialType.SUPERNET));

            setRange(form, '10.0.0.0/8');
            setType(form, 'ipv4');
            tick(DEBOUNCE_MS);

            handle.destroy();
            api.validateSupernet.calls.reset();
            setType(form, 'ipv6');
            tick(DEBOUNCE_MS);
            expect(api.validateSupernet).not.toHaveBeenCalled();
        }));

        it('is idempotent', () => {
            const handle = service.attach(buildForm(), buildType(SpecialType.SUPERNET));
            handle.destroy();
            expect(() => handle.destroy()).not.toThrow();
        });
    });
});
