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
import { TestBed } from '@angular/core/testing';
import { UntypedFormControl, UntypedFormGroup } from '@angular/forms';
import { Subject, of, throwError } from 'rxjs';

import { CmdbMultiDataSection } from '../../../../models/cmdb-type';
import { MultiDataSectionSet } from '../../../../models/cmdb-object';
import { MdsRowValidatorHandle, MdsValidationState } from '../../../sections/multi-data-section/mds-row-validator';
import {
    IPAM_INTERFACE_FIELD_NAMES,
    IPAM_INTERFACE_REQUIRED_FIELDS,
    IPAM_INTERFACE_SECTION_NAME
} from '../models/interface-fields';
import { InterfaceValidationResponse } from '../models/interface-validation.types';
import { InterfaceIpamApiService } from './interface-ipam-api.service';
import { InterfaceMdsValidatorService } from './interface-mds-validator.service';
/* ------------------------------------------------------------------------------------------------------------------ */


describe('InterfaceMdsValidatorService', () => {
    let service: InterfaceMdsValidatorService;
    let api: jasmine.SpyObj<InterfaceIpamApiService>;

    function buildIpamForm(omit?: string): UntypedFormGroup {
        const form = new UntypedFormGroup({});
        for (const fieldName of IPAM_INTERFACE_REQUIRED_FIELDS) {
            if (fieldName === omit) {
                continue;
            }
            form.addControl(fieldName, new UntypedFormControl(''));
        }
        return form;
    }

    function buildIpamSection(overrides: Partial<CmdbMultiDataSection> = {}): CmdbMultiDataSection {
        return {
            type: 'multi-data-section',
            name: IPAM_INTERFACE_SECTION_NAME,
            label: 'Interfaces',
            fields: [...IPAM_INTERFACE_REQUIRED_FIELDS],
            hidden_fields: [],
            ...overrides
        } as CmdbMultiDataSection;
    }

    function buildRow(rowId: number, subnet: unknown, ip: unknown): MultiDataSectionSet {
        return {
            multi_data_id: rowId,
            data: [
                { name: IPAM_INTERFACE_FIELD_NAMES.SUBNET, value: subnet },
                { name: IPAM_INTERFACE_FIELD_NAMES.IP_ADDRESS, value: ip }
            ]
        };
    }

    function readState(handle: MdsRowValidatorHandle): MdsValidationState {
        let captured: MdsValidationState | undefined;
        const sub = handle.state$.subscribe(state => captured = state);
        sub.unsubscribe();
        return captured!;
    }

    beforeEach(() => {
        api = jasmine.createSpyObj<InterfaceIpamApiService>(
            'InterfaceIpamApiService',
            ['validateInterface']
        );

        TestBed.configureTestingModule({
            providers: [
                InterfaceMdsValidatorService,
                { provide: InterfaceIpamApiService, useValue: api }
            ]
        });

        service = TestBed.inject(InterfaceMdsValidatorService);
    });


    describe('attach()', () => {
        it('returns null when the section is missing', () => {
            const result = service.attach(buildIpamForm(), undefined as any, { excludeObjectId: null });
            expect(result).toBeNull();
        });

        it('returns null when section.name is not the IPAM interface section', () => {
            const section = buildIpamSection({ name: 'some-other-multi-data-section' });
            expect(service.attach(buildIpamForm(), section, { excludeObjectId: null })).toBeNull();
        });

        // One opt-out test per required field, so future field additions auto-extend coverage
        for (const fieldName of IPAM_INTERFACE_REQUIRED_FIELDS) {
            it(`returns null when required field '${fieldName}' is missing from the form`, () => {
                const result = service.attach(
                    buildIpamForm(fieldName),
                    buildIpamSection(),
                    { excludeObjectId: null }
                );
                expect(result).toBeNull();
            });
        }

        it('returns an active handle when the section name and full schema are present', () => {
            const handle = service.attach(buildIpamForm(), buildIpamSection(), { excludeObjectId: null });
            expect(handle).not.toBeNull();
            expect(handle?.state$).toBeDefined();
            expect(typeof handle?.validate).toBe('function');
            expect(typeof handle?.destroy).toBe('function');
            handle?.destroy();
        });
    });


    describe('handle.state$', () => {
        it('emits a permanently-valid default state on initial subscribe', () => {
            const handle = service.attach(buildIpamForm(), buildIpamSection(), { excludeObjectId: null })!;
            const state = readState(handle);

            expect(state.valid).toBeTrue();
            expect(state.invalidRowIndices.length).toBe(0);

            handle.destroy();
        });
    });


    describe('handle.validate()', () => {
        it('emits a valid state and skips the API entirely when there are no rows', () => {
            const handle = service.attach(buildIpamForm(), buildIpamSection(), { excludeObjectId: null })!;

            handle.validate([]);

            expect(api.validateInterface).not.toHaveBeenCalled();
            expect(readState(handle).valid).toBeTrue();

            handle.destroy();
        });

        it('builds a payload containing every row plus the excludeObjectId verbatim', () => {
            api.validateInterface.and.returnValue(of({ valid: true, errors: [] } as InterfaceValidationResponse));
            const handle = service.attach(buildIpamForm(), buildIpamSection(), { excludeObjectId: 24 })!;

            handle.validate([
                buildRow(0, 5, '10.0.0.1'),
                buildRow(1, 5, '10.0.0.2')
            ]);

            expect(api.validateInterface).toHaveBeenCalledTimes(1);
            const payload = api.validateInterface.calls.mostRecent().args[0];
            expect(payload.exclude_object_id).toBe(24);
            expect(payload.rows.length).toBe(2);
            expect(payload.rows[0]).toEqual({ row_index: 0, subnet_id: 5, ip_address: '10.0.0.1' });
            expect(payload.rows[1]).toEqual({ row_index: 1, subnet_id: 5, ip_address: '10.0.0.2' });

            handle.destroy();
        });

        it('passes through a null excludeObjectId when in object create mode', () => {
            api.validateInterface.and.returnValue(of({ valid: true, errors: [] } as InterfaceValidationResponse));
            const handle = service.attach(buildIpamForm(), buildIpamSection(), { excludeObjectId: null })!;

            handle.validate([buildRow(0, 5, '10.0.0.1')]);

            expect(api.validateInterface.calls.mostRecent().args[0].exclude_object_id).toBeNull();
            handle.destroy();
        });

        it('normalizes empty / whitespace / non-string IP values to null', () => {
            api.validateInterface.and.returnValue(of({ valid: true, errors: [] } as InterfaceValidationResponse));
            const handle = service.attach(buildIpamForm(), buildIpamSection(), { excludeObjectId: null })!;

            handle.validate([
                buildRow(0, 5, ''),
                buildRow(1, 5, '   '),
                buildRow(2, 5, 12345),
                buildRow(3, 5, null)
            ]);

            const ips = api.validateInterface.calls.mostRecent().args[0].rows.map(r => r.ip_address);
            expect(ips).toEqual([null, null, null, null]);

            handle.destroy();
        });

        it('normalizes non-positive / non-numeric subnet refs to null', () => {
            api.validateInterface.and.returnValue(of({ valid: true, errors: [] } as InterfaceValidationResponse));
            const handle = service.attach(buildIpamForm(), buildIpamSection(), { excludeObjectId: null })!;

            handle.validate([
                buildRow(0, 0, '10.0.0.1'),
                buildRow(1, -1, '10.0.0.2'),
                buildRow(2, 'abc', '10.0.0.3'),
                buildRow(3, null, '10.0.0.4')
            ]);

            const subnets = api.validateInterface.calls.mostRecent().args[0].rows.map(r => r.subnet_id);
            expect(subnets).toEqual([null, null, null, null]);

            handle.destroy();
        });

        it('keeps the state valid when the backend returns valid:true', () => {
            api.validateInterface.and.returnValue(of({ valid: true, errors: [] } as InterfaceValidationResponse));
            const handle = service.attach(buildIpamForm(), buildIpamSection(), { excludeObjectId: null })!;

            handle.validate([buildRow(0, 5, '10.0.0.1')]);

            const state = readState(handle);
            expect(state.valid).toBeTrue();
            expect(state.invalidRowIndices.length).toBe(0);

            handle.destroy();
        });

        it('extracts row_index from per-row errors into invalidRowIndices', () => {
            api.validateInterface.and.returnValue(of({
                valid: false,
                errors: [
                    { code: 'ip_invalid', message: 'bad', details: { row_index: 2 } }
                ]
            } as InterfaceValidationResponse));
            const handle = service.attach(buildIpamForm(), buildIpamSection(), { excludeObjectId: null })!;

            handle.validate([buildRow(0, 5, '10.0.0.1'), buildRow(2, 5, 'bad')]);

            const state = readState(handle);
            expect(state.valid).toBeFalse();
            expect(Array.from(state.invalidRowIndices)).toEqual([2]);

            handle.destroy();
        });

        it('extracts both first_row_index and duplicate_row_index from cross-row dupes', () => {
            api.validateInterface.and.returnValue(of({
                valid: false,
                errors: [{
                    code: 'ip_duplicate',
                    message: 'dupe',
                    details: { first_row_index: 0, duplicate_row_index: 3 }
                }]
            } as InterfaceValidationResponse));
            const handle = service.attach(buildIpamForm(), buildIpamSection(), { excludeObjectId: null })!;

            handle.validate([buildRow(0, 5, '10.0.0.1'), buildRow(3, 5, '10.0.0.1')]);

            const state = readState(handle);
            expect(state.valid).toBeFalse();
            expect(Array.from(state.invalidRowIndices).sort()).toEqual([0, 3]);

            handle.destroy();
        });

        it('deduplicates indices when several errors flag the same row', () => {
            api.validateInterface.and.returnValue(of({
                valid: false,
                errors: [
                    { code: 'a', message: 'a', details: { row_index: 1 } },
                    { code: 'b', message: 'b', details: { row_index: 1 } },
                    { code: 'c', message: 'c', details: { duplicate_row_index: 1 } }
                ]
            } as InterfaceValidationResponse));
            const handle = service.attach(buildIpamForm(), buildIpamSection(), { excludeObjectId: null })!;

            handle.validate([buildRow(1, 5, '10.0.0.1')]);

            expect(Array.from(readState(handle).invalidRowIndices)).toEqual([1]);

            handle.destroy();
        });

        it('ignores non-numeric values in details.row_index', () => {
            api.validateInterface.and.returnValue(of({
                valid: false,
                errors: [
                    { code: 'a', message: 'a', details: { row_index: 'oops' } },
                    { code: 'b', message: 'b', details: { row_index: 2 } }
                ]
            } as InterfaceValidationResponse));
            const handle = service.attach(buildIpamForm(), buildIpamSection(), { excludeObjectId: null })!;

            handle.validate([buildRow(2, 5, 'bad')]);

            expect(Array.from(readState(handle).invalidRowIndices)).toEqual([2]);

            handle.destroy();
        });

        it('falls back to a valid state when the API errors out', () => {
            api.validateInterface.and.returnValue(throwError(() => new Error('boom')));
            const handle = service.attach(buildIpamForm(), buildIpamSection(), { excludeObjectId: null })!;

            handle.validate([buildRow(0, 5, '10.0.0.1')]);

            const state = readState(handle);
            expect(state.valid).toBeTrue();
            expect(state.invalidRowIndices.length).toBe(0);

            handle.destroy();
        });

        it('cancels an in-flight request when validate() is called again (switchMap)', () => {
            const firstCall = new Subject<InterfaceValidationResponse>();
            const secondCall = new Subject<InterfaceValidationResponse>();
            api.validateInterface.and.returnValues(firstCall.asObservable(), secondCall.asObservable());

            const handle = service.attach(buildIpamForm(), buildIpamSection(), { excludeObjectId: null })!;

            handle.validate([buildRow(0, 5, '10.0.0.1')]);
            handle.validate([buildRow(0, 5, '10.0.0.2')]);

            // First call's late response must be ignored; only the second call's result wins.
            firstCall.next({
                valid: false,
                errors: [{ code: 'x', message: 'x', details: { row_index: 0 } }]
            } as InterfaceValidationResponse);
            secondCall.next({ valid: true, errors: [] } as InterfaceValidationResponse);

            const state = readState(handle);
            expect(state.valid).toBeTrue();
            expect(state.invalidRowIndices.length).toBe(0);

            handle.destroy();
        });
    });


    describe('handle.destroy()', () => {
        it('does not throw when called repeatedly', () => {
            const handle = service.attach(buildIpamForm(), buildIpamSection(), { excludeObjectId: null })!;
            handle.destroy();
            // A second destroy must be a tolerated no-op so the MDS component doesn't have to track state.
            expect(() => handle.destroy()).not.toThrow();
        });

        it('completes state$ so consumers receive a complete notification', () => {
            const handle = service.attach(buildIpamForm(), buildIpamSection(), { excludeObjectId: null })!;
            let completed = false;
            handle.state$.subscribe({ complete: () => completed = true });

            handle.destroy();

            expect(completed).toBeTrue();
        });
    });
});
