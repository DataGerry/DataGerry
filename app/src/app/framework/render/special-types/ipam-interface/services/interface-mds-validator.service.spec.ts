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
import { of, throwError } from 'rxjs';

import { CmdbMultiDataSection } from '../../../../models/cmdb-type';
import { MultiDataSectionSet } from '../../../../models/cmdb-object';
import {
    MdsCandidateValidationState,
    MdsRowValidatorHandle
} from '../../../sections/multi-data-section/mds-row-validator';
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

    function buildRow(rowId: number, subnet: unknown, ip: unknown, type?: unknown): MultiDataSectionSet {
        const data: MultiDataSectionSet['data'] = [
            { name: IPAM_INTERFACE_FIELD_NAMES.SUBNET, value: subnet },
            { name: IPAM_INTERFACE_FIELD_NAMES.IP_ADDRESS, value: ip }
        ];

        if (type !== undefined) {
            data.push({ name: IPAM_INTERFACE_FIELD_NAMES.TYPE, value: type });
        }

        return { multi_data_id: rowId, data };
    }

    function buildCandidate(subnet: unknown, ip: unknown, type?: unknown): Record<string, unknown> {
        const candidate: Record<string, unknown> = {
            [IPAM_INTERFACE_FIELD_NAMES.SUBNET]: subnet,
            [IPAM_INTERFACE_FIELD_NAMES.IP_ADDRESS]: ip
        };

        if (type !== undefined) {
            candidate[IPAM_INTERFACE_FIELD_NAMES.TYPE] = type;
        }

        return candidate;
    }

    function readState(observable: ReturnType<MdsRowValidatorHandle['validateCandidate']>): MdsCandidateValidationState {
        let captured: MdsCandidateValidationState | undefined;
        observable.subscribe(state => captured = state).unsubscribe();
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
            const result = service.attach(undefined as any, { excludeObjectId: null });
            expect(result).toBeNull();
        });

        it('returns null when section.name is not the IPAM interface section', () => {
            const section = buildIpamSection({ name: 'some-other-multi-data-section' });
            expect(service.attach(section, { excludeObjectId: null })).toBeNull();
        });

        // One opt-out test per required field, so future field additions auto-extend coverage
        for (const fieldName of IPAM_INTERFACE_REQUIRED_FIELDS) {
            it(`returns null when required field '${fieldName}' is missing from the section`, () => {
                const fields = IPAM_INTERFACE_REQUIRED_FIELDS.filter(f => f !== fieldName);
                const result = service.attach(
                    buildIpamSection({ fields: [...fields] }),
                    { excludeObjectId: null }
                );
                expect(result).toBeNull();
            });
        }

        it('returns an active handle when the section name and full schema are present', () => {
            const handle = service.attach(buildIpamSection(), { excludeObjectId: null });
            expect(handle).not.toBeNull();
            expect(handle?.errorAnchorField).toBe(IPAM_INTERFACE_FIELD_NAMES.IP_ADDRESS);
            expect(typeof handle?.validateCandidate).toBe('function');
            expect(typeof handle?.destroy).toBe('function');
            handle?.destroy();
        });
    });


    describe('handle.validateCandidate()', () => {
        it('sends every committed row plus the candidate (add mode) with a fresh row index', () => {
            api.validateInterface.and.returnValue(of({ valid: true, errors: [] } as InterfaceValidationResponse));
            const handle = service.attach(buildIpamSection(), { excludeObjectId: 24 })!;

            const committed = [
                buildRow(0, 5, '10.0.0.1'),
                buildRow(1, 5, '10.0.0.2')
            ];

            readState(handle.validateCandidate(
                committed,
                buildCandidate(5, '10.0.0.3'),
                /* editingRowId */ null
            ));

            expect(api.validateInterface).toHaveBeenCalledTimes(1);
            const payload = api.validateInterface.calls.mostRecent().args[0];
            expect(payload.exclude_object_id).toBe(24);
            expect(payload.rows.length).toBe(3);
            expect(payload.rows[0]).toEqual({ row_index: 0, subnet_id: 5, ip_address: '10.0.0.1', interface_type: 'ipv4' });
            expect(payload.rows[1]).toEqual({ row_index: 1, subnet_id: 5, ip_address: '10.0.0.2', interface_type: 'ipv4' });
            // Candidate gets max(existing)+1 in add mode so the backend can distinguish it.
            expect(payload.rows[2]).toEqual({ row_index: 2, subnet_id: 5, ip_address: '10.0.0.3', interface_type: 'ipv4' });

            handle.destroy();
        });

        it('uses row index 0 when there are no committed rows yet', () => {
            api.validateInterface.and.returnValue(of({ valid: true, errors: [] } as InterfaceValidationResponse));
            const handle = service.attach(buildIpamSection(), { excludeObjectId: null })!;

            readState(handle.validateCandidate([], buildCandidate(5, '10.0.0.1'), null));

            const payload = api.validateInterface.calls.mostRecent().args[0];
            expect(payload.rows).toEqual([{ row_index: 0, subnet_id: 5, ip_address: '10.0.0.1', interface_type: 'ipv4' }]);
            handle.destroy();
        });

        it('replaces the edited row in the payload when editingRowId is set', () => {
            api.validateInterface.and.returnValue(of({ valid: true, errors: [] } as InterfaceValidationResponse));
            const handle = service.attach(buildIpamSection(), { excludeObjectId: null })!;

            const committed = [
                buildRow(0, 5, '10.0.0.1'),
                buildRow(1, 5, '10.0.0.2'),
                buildRow(2, 5, '10.0.0.3')
            ];

            readState(handle.validateCandidate(
                committed,
                buildCandidate(5, '10.0.0.99'),
                /* editingRowId */ 1
            ));

            const payload = api.validateInterface.calls.mostRecent().args[0];
            expect(payload.rows.length).toBe(3);
            // Row 1 is excluded from the committed copies and re-added as the candidate.
            expect(payload.rows.map(r => r.row_index).sort()).toEqual([0, 1, 2]);
            const edited = payload.rows.find(r => r.row_index === 1);
            expect(edited).toEqual({ row_index: 1, subnet_id: 5, ip_address: '10.0.0.99', interface_type: 'ipv4' });

            handle.destroy();
        });

        it('passes through a null excludeObjectId when in object create mode', () => {
            api.validateInterface.and.returnValue(of({ valid: true, errors: [] } as InterfaceValidationResponse));
            const handle = service.attach(buildIpamSection(), { excludeObjectId: null })!;

            readState(handle.validateCandidate([], buildCandidate(5, '10.0.0.1'), null));

            expect(api.validateInterface.calls.mostRecent().args[0].exclude_object_id).toBeNull();
            handle.destroy();
        });

        it('does not call the backend until an IP-Address is entered', () => {
            const handle = service.attach(buildIpamSection(), { excludeObjectId: null })!;

            const emptyIps: unknown[] = ['', '   ', 12345, null, undefined];
            for (const value of emptyIps) {
                api.validateInterface.calls.reset();
                readState(handle.validateCandidate([], buildCandidate(5, value), null));
                expect(api.validateInterface).not.toHaveBeenCalled();
            }

            handle.destroy();
        });

        it('flags the IP-Address as required when a network is selected without one', () => {
            const handle = service.attach(buildIpamSection(), { excludeObjectId: null })!;

            const state = readState(handle.validateCandidate([], buildCandidate(5, ''), null));

            expect(state.valid).toBeFalse();
            expect(state.errors.length).toBeGreaterThan(0);
            expect(api.validateInterface).not.toHaveBeenCalled();

            handle.destroy();
        });

        it('stays valid without a backend call when neither network nor IP is set', () => {
            const handle = service.attach(buildIpamSection(), { excludeObjectId: null })!;

            const state = readState(handle.validateCandidate([], buildCandidate(0, ''), null));

            expect(state.valid).toBeTrue();
            expect(state.errors.length).toBe(0);
            expect(api.validateInterface).not.toHaveBeenCalled();

            handle.destroy();
        });

        it('treats the network as optional and validates an IP entered on its own', () => {
            api.validateInterface.and.returnValue(of({ valid: true, errors: [] } as InterfaceValidationResponse));
            const handle = service.attach(buildIpamSection(), { excludeObjectId: null })!;

            readState(handle.validateCandidate([], buildCandidate(0, '10.0.0.1'), null));

            expect(api.validateInterface).toHaveBeenCalledTimes(1);
            expect(api.validateInterface.calls.mostRecent().args[0].rows[0].subnet_id).toBeNull();

            handle.destroy();
        });

        it('normalizes non-positive / non-numeric subnet refs in the candidate to null', () => {
            api.validateInterface.and.returnValue(of({ valid: true, errors: [] } as InterfaceValidationResponse));
            const handle = service.attach(buildIpamSection(), { excludeObjectId: null })!;

            const cases: unknown[] = [0, -1, 'abc', null, undefined];
            for (const value of cases) {
                api.validateInterface.calls.reset();
                readState(handle.validateCandidate([], buildCandidate(value, '10.0.0.1'), null));
                expect(api.validateInterface.calls.mostRecent().args[0].rows[0].subnet_id).toBeNull();
            }

            handle.destroy();
        });

        it('sends the selected interface type for committed rows and the candidate', () => {
            api.validateInterface.and.returnValue(of({ valid: true, errors: [] } as InterfaceValidationResponse));
            const handle = service.attach(buildIpamSection(), { excludeObjectId: null })!;

            const committed = [buildRow(0, 5, '2001:db8::1', 'ipv6')];

            readState(handle.validateCandidate(
                committed,
                buildCandidate(5, '2001:db8::2', 'ipv6'),
                null
            ));

            const payload = api.validateInterface.calls.mostRecent().args[0];
            expect(payload.rows.map(r => r.interface_type)).toEqual(['ipv6', 'ipv6']);

            handle.destroy();
        });

        it('falls back to ipv4 when no interface type is selected', () => {
            api.validateInterface.and.returnValue(of({ valid: true, errors: [] } as InterfaceValidationResponse));
            const handle = service.attach(buildIpamSection(), { excludeObjectId: null })!;

            readState(handle.validateCandidate([], buildCandidate(5, '10.0.0.1'), null));

            expect(api.validateInterface.calls.mostRecent().args[0].rows[0].interface_type).toBe('ipv4');
            handle.destroy();
        });

        it('returns valid:true and no errors when the backend says valid', () => {
            api.validateInterface.and.returnValue(of({ valid: true, errors: [] } as InterfaceValidationResponse));
            const handle = service.attach(buildIpamSection(), { excludeObjectId: null })!;

            const state = readState(handle.validateCandidate([], buildCandidate(5, '10.0.0.1'), null));
            expect(state.valid).toBeTrue();
            expect(state.errors.length).toBe(0);

            handle.destroy();
        });

        it('returns valid:false with all error messages from the backend response', () => {
            api.validateInterface.and.returnValue(of({
                valid: false,
                errors: [
                    { code: 'ip_invalid', message: 'Bad IP', details: {} },
                    { code: 'ip_duplicate', message: 'Already in use', details: {} }
                ]
            } as InterfaceValidationResponse));
            const handle = service.attach(buildIpamSection(), { excludeObjectId: null })!;

            const state = readState(handle.validateCandidate([], buildCandidate(5, 'bad'), null));
            expect(state.valid).toBeFalse();
            expect(Array.from(state.errors)).toEqual(['Bad IP', 'Already in use']);

            handle.destroy();
        });

        it('skips errors that have no message string', () => {
            api.validateInterface.and.returnValue(of({
                valid: false,
                errors: [
                    { code: 'a', message: '', details: {} },
                    { code: 'b', message: 'real', details: {} }
                ]
            } as InterfaceValidationResponse));
            const handle = service.attach(buildIpamSection(), { excludeObjectId: null })!;

            const state = readState(handle.validateCandidate([], buildCandidate(5, '10.0.0.1'), null));
            expect(Array.from(state.errors)).toEqual(['real']);

            handle.destroy();
        });

        it('falls back to a valid state when the API errors out', () => {
            api.validateInterface.and.returnValue(throwError(() => new Error('boom')));
            const handle = service.attach(buildIpamSection(), { excludeObjectId: null })!;

            const state = readState(handle.validateCandidate([], buildCandidate(5, '10.0.0.1'), null));
            expect(state.valid).toBeTrue();
            expect(state.errors.length).toBe(0);

            handle.destroy();
        });
    });


    describe('handle.destroy()', () => {
        it('does not throw when called repeatedly', () => {
            const handle = service.attach(buildIpamSection(), { excludeObjectId: null })!;
            handle.destroy();
            expect(() => handle.destroy()).not.toThrow();
        });
    });
});
