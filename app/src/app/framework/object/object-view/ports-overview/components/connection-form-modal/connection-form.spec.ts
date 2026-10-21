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
import {
    CableCiPayload,
    CableManagementMode,
    CableSource,
    CmdbPortConnection,
    ConnectionType,
    ResolvedCable
} from '../../models/port-connection.types';
import { ConnectionForm, ConnectionStep } from './connection-form';
/* ------------------------------------------------------------------------------------------------------------------ */

function storedCable(overrides: Partial<ResolvedCable> = {}): ResolvedCable {
    return {
        source: CableSource.INLINE,
        cable_ci_id: null,
        name: 'Patch A-12',
        type: 'CAT5e',
        type_id: 9932,
        length: '3 m',
        color: 'blue',
        description: null,
        ...overrides
    };
}

function storedConnection(overrides: Partial<CmdbPortConnection> = {}): CmdbPortConnection {
    return {
        public_id: 5,
        endpoints: [9940, 9942],
        connection_type: ConnectionType.CABLE,
        cable: storedCable(),
        author_id: 1,
        creation_time: null,
        last_edit_time: null,
        ...overrides
    };
}


describe('ConnectionForm', () => {
    let form: ConnectionForm;

    beforeEach(() => form = new ConnectionForm());

    describe('creating', () => {
        it('refuses to be submitted without a far end', () => {
            expect(form.group.invalid).toBeTrue();

            form.group.patchValue({ farEndPortId: 9942 });

            expect(form.group.valid).toBeTrue();
        });

        it('sends the two ports as a cable connection', () => {
            form.group.patchValue({ farEndPortId: 9942 });

            const payload = form.toCreatePayload(9940);

            expect(payload.endpoints).toEqual([9940, 9942]);
            expect(payload.connection_type).toBe(ConnectionType.CABLE);
        });

        it('describes the cable on the connection itself while it is managed as metadata', () => {
            form.group.patchValue({
                farEndPortId: 9940,
                cableName: 'Patch A-12',
                cableType: '9960',
                cableLength: '1.5 m',
                cableColor: 'grey'
            });

            expect(form.toCreatePayload(9942)).toEqual({
                endpoints: [9942, 9940],
                connection_type: ConnectionType.CABLE,
                cable_name: 'Patch A-12',
                cable_type: 9960,
                cable_length: '1.5 m',
                cable_color: 'grey',
                cable_description: null
            });
        });

        it('names the linked cable and nothing else once one is picked', () => {
            form.group.patchValue({ farEndPortId: 9941 });
            form.selectManagementMode(CableManagementMode.CABLE_CI);
            form.group.patchValue({ cableCiId: 9932 });

            expect(form.toCreatePayload(9943)).toEqual({
                endpoints: [9943, 9941],
                connection_type: ConnectionType.CABLE,
                cable_ci_id: 9932
            });
        });

        it('sends an empty field as null and never as an empty string', () => {
            form.group.patchValue({ farEndPortId: 9942, cableName: '   ' });

            expect(form.toCableInfo()).toEqual({
                cable_name: null,
                cable_type: null,
                cable_length: null,
                cable_color: null,
                cable_description: null
            });
        });

        it('sends the picked cable type as a number', () => {
            form.group.patchValue({ cableType: '9932', cableLength: ' 3 m ' });

            expect(form.cableMetadata().cable_type).toBe(9932);
            expect(form.cableMetadata().cable_length).toBe('3 m');
        });
    });


    describe('cable management', () => {
        it('starts as metadata and omits the cable CI key entirely', () => {
            expect(form.managementMode).toBe(CableManagementMode.METADATA);
            expect('cable_ci_id' in form.toCableInfo()).toBeFalse();
        });

        it('requires a cable CI once the user asks to link one', () => {
            form.selectManagementMode(CableManagementMode.CABLE_CI);

            expect(form.group.controls.cableCiId.valid).toBeFalse();

            form.group.patchValue({ cableCiId: 4711 });

            expect(form.toCableInfo()).toEqual({ cable_ci_id: 4711 });
        });


        it('sends the reference alone, so the linked cable stays the one place the values live', () => {
            form.group.patchValue({ cableName: 'patch 1-12', cableLength: '3 m' });
            form.selectManagementMode(CableManagementMode.CABLE_CI);
            form.group.patchValue({ cableCiId: 4711 });

            expect(Object.keys(form.toCableInfo())).toEqual(['cable_ci_id']);
        });


        it('forgets metadata the user typed before switching, so the review cannot claim it', () => {
            form.group.patchValue({ cableName: 'patch 1-12', cableType: '9932' });

            form.selectManagementMode(CableManagementMode.CABLE_CI);

            expect(form.cableMetadata().cable_name).toBeNull();
            expect(form.cableMetadata().cable_type).toBeNull();
        });

        it('drops the reference again when the user goes back to metadata', () => {
            form.selectManagementMode(CableManagementMode.CABLE_CI);
            form.group.patchValue({ cableCiId: 4711 });

            form.selectManagementMode(CableManagementMode.METADATA);

            expect(form.group.controls.cableCiId.value).toBeNull();
            expect('cable_ci_id' in form.toCableInfo()).toBeFalse();
        });
    });


    describe('editing', () => {
        beforeEach(() => {
            form.lockEndpoints();
            form.prefill(storedConnection());
        });

        it('is submittable although the far end is not part of the form', () => {
            expect(form.group.valid).toBeTrue();
        });

        it('prefills the stored cable, option ids as select values', () => {
            expect(form.group.controls.cableName.value).toBe('Patch A-12');
            expect(form.group.controls.cableType.value).toBe('9932');
            expect(form.group.controls.cableLength.value).toBe('3 m');
        });

        it('opens in the mode the cable reports as its source', () => {
            expect(form.managementMode).toBe(CableManagementMode.METADATA);

            const linked = new ConnectionForm();
            linked.prefill(storedConnection({
                cable: storedCable({ source: CableSource.CI, cable_ci_id: 4711, type_id: null })
            }));

            expect(linked.managementMode).toBe(CableManagementMode.CABLE_CI);
            expect((linked.toCableInfo() as CableCiPayload).cable_ci_id).toBe(4711);
        });


        it('starts an inventoried cable with no cable type - a CI stores the label, not an option', () => {
            const linked = new ConnectionForm();
            linked.prefill(storedConnection({
                cable: storedCable({ source: CableSource.CI, cable_ci_id: 4711, type: 'CAT6', type_id: null })
            }));

            linked.selectManagementMode(CableManagementMode.METADATA);

            expect(linked.group.controls.cableType.value).toBeNull();
        });


        it('reads a link with no cable at all without failing', () => {
            const paired = new ConnectionForm();

            paired.prefill(storedConnection({ cable: null }));

            expect(paired.managementMode).toBe(CableManagementMode.METADATA);
            expect(paired.cableMetadata().cable_name).toBeNull();
        });
    });


    describe('wizard steps', () => {
        it('asks for the cable only while it is described here', () => {
            expect(form.activeSteps()).toEqual([
                ConnectionStep.ENDPOINTS,
                ConnectionStep.MANAGEMENT,
                ConnectionStep.CABLE,
                ConnectionStep.REVIEW
            ]);

            form.selectManagementMode(CableManagementMode.CABLE_CI);

            expect(form.activeSteps()).toEqual([
                ConnectionStep.ENDPOINTS,
                ConnectionStep.MANAGEMENT,
                ConnectionStep.REVIEW
            ]);
        });

        it('holds the far end back until it is chosen', () => {
            expect(form.isStepValid(ConnectionStep.ENDPOINTS)).toBeFalse();

            form.group.patchValue({ farEndPortId: 9942 });

            expect(form.isStepValid(ConnectionStep.ENDPOINTS)).toBeTrue();
        });

        it('lets an edit past the endpoint step, which it cannot change anyway', () => {
            form.lockEndpoints();

            expect(form.isStepValid(ConnectionStep.ENDPOINTS)).toBeTrue();
        });

        it('holds the management step back while a linked cable is missing', () => {
            form.group.patchValue({ farEndPortId: 9942 });
            form.selectManagementMode(CableManagementMode.CABLE_CI);

            expect(form.isStepValid(ConnectionStep.MANAGEMENT)).toBeFalse();

            form.group.patchValue({ cableCiId: 4711 });

            expect(form.isStepValid(ConnectionStep.MANAGEMENT)).toBeTrue();
        });

        it('reports a missing answer only once the step was tried', () => {
            expect(form.farEndError).toBe('');

            form.markStepTouched(ConnectionStep.ENDPOINTS);

            expect(form.farEndError).toBe('Choose the port this cable runs to.');
        });
    });


    describe('messages', () => {
        it('stays quiet until the user has left the field', () => {
            form.group.controls.cableName.setValue('x'.repeat(300));

            expect(form.errorOf('cableName')).toBe('');

            form.group.controls.cableName.markAsTouched();

            expect(form.errorOf('cableName')).toBe('This value is too long.');
        });
    });
});
