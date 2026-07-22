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
import { SUBNET_FIELD_NAMES } from '../models/subnet-fields';
import { SubnetValidationResponse } from '../models/subnet-validation.types';
import { SubnetIpamApiService } from './subnet-ipam-api.service';
import {
    BACKEND_VALIDATION_ERROR_KEY,
    SubnetNetworkRangeValidatorService
} from './subnet-network-range-validator.service';
/* ------------------------------------------------------------------------------------------------------------------ */


describe('SubnetNetworkRangeValidatorService', () => {
    let service: SubnetNetworkRangeValidatorService;
    let api: jasmine.SpyObj<SubnetIpamApiService>;

    /** Mirrors the private DEBOUNCE_MS in the service under test. */
    const DEBOUNCE_MS = 400;

    function buildType(specialType?: SpecialType | string | null): CmdbType {
        return { special_type: specialType } as unknown as CmdbType;
    }

    function buildForm(opts: {
        networkRange?: boolean;
        supernet?: boolean;
        subnetType?: boolean;
        rangeValidators?: ValidatorFn[];
    } = {}): UntypedFormGroup {
        const controls: Record<string, UntypedFormControl> = {};

        if (opts.networkRange ?? true) {
            controls[SUBNET_FIELD_NAMES.NETWORK_RANGE] = new UntypedFormControl('', opts.rangeValidators ?? []);
        }

        if (opts.supernet ?? true) {
            controls[SUBNET_FIELD_NAMES.SUPERNET] = new UntypedFormControl('');
        }

        // dg-subnet-type is optional: older subnet types may not declare it.
        if (opts.subnetType ?? true) {
            controls[SUBNET_FIELD_NAMES.SUBNET_TYPE] = new UntypedFormControl('');
        }

        return new UntypedFormGroup(controls);
    }

    function setRange(form: UntypedFormGroup, value: unknown): void {
        form.get(SUBNET_FIELD_NAMES.NETWORK_RANGE)!.setValue(value);
    }

    function setSupernetRef(form: UntypedFormGroup, value: unknown): void {
        form.get(SUBNET_FIELD_NAMES.SUPERNET)!.setValue(value);
    }

    function setSubnetType(form: UntypedFormGroup, value: unknown): void {
        form.get(SUBNET_FIELD_NAMES.SUBNET_TYPE)!.setValue(value);
    }

    function rangeErrors(form: UntypedFormGroup): Record<string, any> | null {
        return form.get(SUBNET_FIELD_NAMES.NETWORK_RANGE)!.errors;
    }

    function lastPayload() {
        return api.validateSubnet.calls.mostRecent().args[0];
    }

    function valid(): SubnetValidationResponse {
        return { valid: true, errors: [] };
    }

    beforeEach(() => {
        api = jasmine.createSpyObj<SubnetIpamApiService>('SubnetIpamApiService', ['validateSubnet']);
        api.validateSubnet.and.returnValue(of(valid()));

        TestBed.configureTestingModule({
            providers: [
                SubnetNetworkRangeValidatorService,
                { provide: SubnetIpamApiService, useValue: api }
            ]
        });

        service = TestBed.inject(SubnetNetworkRangeValidatorService);
    });


    describe('attach() gating — only an active SUBNET form is wired', () => {
        const inertCases: Array<[string, CmdbType | undefined]> = [
            ['typeInstance is undefined', undefined],
            ['special_type is undefined (a normal object)', buildType(undefined)],
            ['special_type is null', buildType(null)],
            ['special_type is SUPERNET', buildType(SpecialType.SUPERNET)],
            ['special_type is VLAN', buildType(SpecialType.VLAN)],
            ['special_type has the wrong case ("subnet")', buildType('subnet')]
        ];

        for (const [label, typeInstance] of inertCases) {
            it(`never calls the backend when ${label}`, fakeAsync(() => {
                const form = buildForm();
                const handle = service.attach(form, typeInstance, { excludeSubnetId: null });

                setSubnetType(form, 'ipv4');
                setSupernetRef(form, 216);
                setRange(form, '10.0.0.0/24');
                tick(DEBOUNCE_MS);

                expect(api.validateSubnet).not.toHaveBeenCalled();
                expect(rangeErrors(form)).toBeNull();
                expect(() => handle.destroy()).not.toThrow();
            }));
        }

        it('is inert and safe when the form is null', () => {
            const handle = service.attach(null as any, buildType(SpecialType.SUBNET), { excludeSubnetId: null });
            expect(() => handle.destroy()).not.toThrow();
        });

        it('is inert when the dg-network-range control is missing', fakeAsync(() => {
            const form = buildForm({ networkRange: false });
            service.attach(form, buildType(SpecialType.SUBNET), { excludeSubnetId: null });

            setSupernetRef(form, 216);
            tick(DEBOUNCE_MS);

            expect(api.validateSubnet).not.toHaveBeenCalled();
        }));

        it('is inert when the dg-supernet-ref control is missing', fakeAsync(() => {
            const form = buildForm({ supernet: false });
            service.attach(form, buildType(SpecialType.SUBNET), { excludeSubnetId: null });

            setRange(form, '10.0.0.0/24');
            tick(DEBOUNCE_MS);

            expect(api.validateSubnet).not.toHaveBeenCalled();
        }));
    });


    describe('subnet_type wiring — present, present-but-empty, and absent', () => {
        it('does NOT call the backend while dg-subnet-type is present but unselected', fakeAsync(() => {
            // Regression: a valid range with no type chosen must not trigger a request
            // the backend would only bounce as "subnet_type is required".
            const form = buildForm({ subnetType: true });
            service.attach(form, buildType(SpecialType.SUBNET), { excludeSubnetId: null });

            setSupernetRef(form, 216);
            setRange(form, '10.0.0.0/24');
            tick(DEBOUNCE_MS);

            expect(api.validateSubnet).not.toHaveBeenCalled();
            expect(rangeErrors(form)).toBeNull();
        }));

        it('includes subnet_type once a type is selected', fakeAsync(() => {
            const form = buildForm({ subnetType: true });
            service.attach(form, buildType(SpecialType.SUBNET), { excludeSubnetId: 7 });

            setSupernetRef(form, 216);
            setSubnetType(form, 'ipv4');
            setRange(form, '10.0.0.0/24');
            tick(DEBOUNCE_MS);

            expect(api.validateSubnet).toHaveBeenCalledTimes(1);
            expect(lastPayload()).toEqual({
                network_range: '10.0.0.0/24',
                parent_supernet_id: 216,
                exclude_subnet_id: 7,
                subnet_type: 'ipv4'
            });
        }));

        it('omits subnet_type entirely for legacy types without the field', fakeAsync(() => {
            const form = buildForm({ subnetType: false });
            service.attach(form, buildType(SpecialType.SUBNET), { excludeSubnetId: null });

            setSupernetRef(form, 216);
            setRange(form, '10.0.0.0/24');
            tick(DEBOUNCE_MS);

            expect(api.validateSubnet).toHaveBeenCalledTimes(1);
            const payload = lastPayload();
            expect(payload).toEqual({
                network_range: '10.0.0.0/24',
                parent_supernet_id: 216,
                exclude_subnet_id: null
            });
            expect('subnet_type' in payload).toBeFalse();
        }));

        it('re-validates when the subnet type changes', fakeAsync(() => {
            const form = buildForm({ subnetType: true });
            service.attach(form, buildType(SpecialType.SUBNET), { excludeSubnetId: null });

            setSupernetRef(form, 216);
            setRange(form, '10.0.0.0/24');
            setSubnetType(form, 'ipv4');
            tick(DEBOUNCE_MS);
            expect(lastPayload().subnet_type).toBe('ipv4');

            api.validateSubnet.calls.reset();
            setSubnetType(form, 'ipv6');
            tick(DEBOUNCE_MS);
            expect(api.validateSubnet).toHaveBeenCalledTimes(1);
            expect(lastPayload().subnet_type).toBe('ipv6');
        }));
    });


    describe('parent_supernet_id derivation from dg-supernet-ref', () => {
        it('coerces and guards the reference value', fakeAsync(() => {
            const form = buildForm({ subnetType: true });
            service.attach(form, buildType(SpecialType.SUBNET), { excludeSubnetId: null });
            setSubnetType(form, 'ipv4');

            const cases: Array<[unknown, number | null]> = [
                ['216', 216],
                [216, 216],
                [3.5, 3.5],
                ['', null],
                [0, null],
                [-1, null],
                ['abc', null],
                [null, null],
                [undefined, null]
            ];

            for (const [input, expected] of cases) {
                api.validateSubnet.calls.reset();
                setSupernetRef(form, input);
                setRange(form, '10.0.0.0/24');
                tick(DEBOUNCE_MS);
                expect(lastPayload().parent_supernet_id)
                    .withContext(`dg-supernet-ref = ${JSON.stringify(input)}`)
                    .toBe(expected as any);
            }
        }));

        it('re-validates when the parent supernet reference changes', fakeAsync(() => {
            const form = buildForm({ subnetType: true });
            service.attach(form, buildType(SpecialType.SUBNET), { excludeSubnetId: null });

            setSubnetType(form, 'ipv4');
            setRange(form, '10.0.0.0/24');
            setSupernetRef(form, 216);
            tick(DEBOUNCE_MS);
            expect(lastPayload().parent_supernet_id).toBe(216);

            api.validateSubnet.calls.reset();
            setSupernetRef(form, 42);
            tick(DEBOUNCE_MS);
            expect(api.validateSubnet).toHaveBeenCalledTimes(1);
            expect(lastPayload().parent_supernet_id).toBe(42);
        }));
    });


    describe('exclude_subnet_id passthrough', () => {
        it('is null in create mode', fakeAsync(() => {
            const form = buildForm({ subnetType: true });
            service.attach(form, buildType(SpecialType.SUBNET), { excludeSubnetId: null });

            setSubnetType(form, 'ipv4');
            setSupernetRef(form, 216);
            setRange(form, '10.0.0.0/24');
            tick(DEBOUNCE_MS);

            expect(lastPayload().exclude_subnet_id).toBeNull();
        }));

        it('carries the edited subnet id in edit mode', fakeAsync(() => {
            const form = buildForm({ subnetType: true });
            service.attach(form, buildType(SpecialType.SUBNET), { excludeSubnetId: 99 });

            setSubnetType(form, 'ipv4');
            setSupernetRef(form, 216);
            setRange(form, '10.0.0.0/24');
            tick(DEBOUNCE_MS);

            expect(lastPayload().exclude_subnet_id).toBe(99);
        }));
    });


    describe('range / debounce / regex behaviour', () => {
        it('does not call the backend for an empty or whitespace-only range', fakeAsync(() => {
            const form = buildForm({ subnetType: true });
            service.attach(form, buildType(SpecialType.SUBNET), { excludeSubnetId: null });
            setSubnetType(form, 'ipv4');
            setSupernetRef(form, 216);

            for (const value of ['', '   ']) {
                api.validateSubnet.calls.reset();
                setRange(form, value);
                tick(DEBOUNCE_MS);
                expect(api.validateSubnet).not.toHaveBeenCalled();
            }
        }));

        it('trims whitespace around the range before sending', fakeAsync(() => {
            const form = buildForm({ subnetType: true });
            service.attach(form, buildType(SpecialType.SUBNET), { excludeSubnetId: null });

            setSubnetType(form, 'ipv4');
            setSupernetRef(form, 216);
            setRange(form, '  10.0.0.0/24  ');
            tick(DEBOUNCE_MS);

            expect(lastPayload().network_range).toBe('10.0.0.0/24');
        }));

        it('debounces rapid range edits and only sends the latest value (switchMap)', fakeAsync(() => {
            const form = buildForm({ subnetType: true });
            service.attach(form, buildType(SpecialType.SUBNET), { excludeSubnetId: null });
            setSubnetType(form, 'ipv4');
            setSupernetRef(form, 216);

            setRange(form, '10.0.0.0/24');
            tick(DEBOUNCE_MS - 200);
            setRange(form, '10.0.1.0/24');
            tick(DEBOUNCE_MS);

            expect(api.validateSubnet).toHaveBeenCalledTimes(1);
            expect(lastPayload().network_range).toBe('10.0.1.0/24');
        }));

        it('skips the backend while the range fails its regex, then calls it once it passes', fakeAsync(() => {
            const CIDR = Validators.pattern(/^\d{1,3}(\.\d{1,3}){3}\/\d{1,2}$/);
            const form = buildForm({ subnetType: true, rangeValidators: [CIDR] });
            service.attach(form, buildType(SpecialType.SUBNET), { excludeSubnetId: null });
            setSubnetType(form, 'ipv4');
            setSupernetRef(form, 216);

            setRange(form, 'nonsense');
            tick(DEBOUNCE_MS);
            expect(api.validateSubnet).not.toHaveBeenCalled();
            expect(rangeErrors(form)?.pattern).toBeTruthy();

            setRange(form, '10.0.0.0/24');
            tick(DEBOUNCE_MS);
            expect(api.validateSubnet).toHaveBeenCalledTimes(1);
        }));
    });


    describe('backend error mapping', () => {
        it('maps a parent-supernet family mismatch to a backendValidation error', fakeAsync(() => {
            api.validateSubnet.and.returnValue(of({
                valid: false,
                errors: [{
                    code: 'parent_supernet_family_mismatch',
                    message: "Candidate 10.0.0.0/24 (ipv4) does not match the address family 'ipv6' of supernet 2001:db8::/32",
                    details: { candidate: '10.0.0.0/24', cidr_family: 'ipv4', supernet_family: 'ipv6', supernet_object_id: 42 }
                }]
            } as SubnetValidationResponse));

            const form = buildForm({ subnetType: true });
            service.attach(form, buildType(SpecialType.SUBNET), { excludeSubnetId: null });
            setSubnetType(form, 'ipv4');
            setSupernetRef(form, 42);
            setRange(form, '10.0.0.0/24');
            tick(DEBOUNCE_MS);

            const error = rangeErrors(form)?.[BACKEND_VALIDATION_ERROR_KEY];
            expect(error).toBeTruthy();
            expect(error.code).toBe('parent_supernet_family_mismatch');
            expect(error.message).toContain('does not match the address family');
        }));

        it('falls back to a default message when invalid with no error details', fakeAsync(() => {
            api.validateSubnet.and.returnValue(of({ valid: false, errors: [] } as SubnetValidationResponse));

            const form = buildForm({ subnetType: true });
            service.attach(form, buildType(SpecialType.SUBNET), { excludeSubnetId: null });
            setSubnetType(form, 'ipv4');
            setSupernetRef(form, 42);
            setRange(form, '10.0.0.0/24');
            tick(DEBOUNCE_MS);

            expect(rangeErrors(form)?.[BACKEND_VALIDATION_ERROR_KEY].message).toBe('Invalid subnet network range.');
        }));

        it('treats a null backend response as valid', fakeAsync(() => {
            api.validateSubnet.and.returnValue(of(null as any));

            const form = buildForm({ subnetType: true });
            service.attach(form, buildType(SpecialType.SUBNET), { excludeSubnetId: null });
            setSubnetType(form, 'ipv4');
            setSupernetRef(form, 42);
            setRange(form, '10.0.0.0/24');
            tick(DEBOUNCE_MS);

            expect(rangeErrors(form)).toBeNull();
        }));

        it('does not block the form when the API errors out', fakeAsync(() => {
            api.validateSubnet.and.returnValue(throwError(() => new Error('network down')));

            const form = buildForm({ subnetType: true });
            service.attach(form, buildType(SpecialType.SUBNET), { excludeSubnetId: null });
            setSubnetType(form, 'ipv4');
            setSupernetRef(form, 42);
            setRange(form, '10.0.0.0/24');
            tick(DEBOUNCE_MS);

            expect(rangeErrors(form)).toBeNull();
        }));
    });


    describe('destroy() — full teardown', () => {
        it('removes the async validator so later edits no longer hit the backend', fakeAsync(() => {
            const form = buildForm({ subnetType: true });
            const handle = service.attach(form, buildType(SpecialType.SUBNET), { excludeSubnetId: null });

            setSubnetType(form, 'ipv4');
            setSupernetRef(form, 216);
            setRange(form, '10.0.0.0/24');
            tick(DEBOUNCE_MS);
            expect(api.validateSubnet).toHaveBeenCalledTimes(1);

            handle.destroy();
            api.validateSubnet.calls.reset();
            setRange(form, '10.0.1.0/24');
            tick(DEBOUNCE_MS);
            expect(api.validateSubnet).not.toHaveBeenCalled();
        }));

        it('stops re-validating on parent / type changes after destroy', fakeAsync(() => {
            const form = buildForm({ subnetType: true });
            const handle = service.attach(form, buildType(SpecialType.SUBNET), { excludeSubnetId: null });

            setSubnetType(form, 'ipv4');
            setSupernetRef(form, 216);
            setRange(form, '10.0.0.0/24');
            tick(DEBOUNCE_MS);

            handle.destroy();
            api.validateSubnet.calls.reset();
            setSupernetRef(form, 42);
            setSubnetType(form, 'ipv6');
            tick(DEBOUNCE_MS);
            expect(api.validateSubnet).not.toHaveBeenCalled();
        }));

        it('is idempotent', () => {
            const handle = service.attach(buildForm(), buildType(SpecialType.SUBNET), { excludeSubnetId: null });
            handle.destroy();
            expect(() => handle.destroy()).not.toThrow();
        });
    });
});
