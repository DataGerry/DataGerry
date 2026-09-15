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
import { PortDeviceKind } from '../../models/port-bulk.types';
import { PortCreateWizardForm } from './port-create-wizard.form';
/* ------------------------------------------------------------------------------------------------------------------ */

describe('PortCreateWizardForm', () => {
    let form: PortCreateWizardForm;

    beforeEach(() => (form = new PortCreateWizardForm()));

    describe('device kind', () => {
        it('demands a rear name from a patch panel', () => {
            form.selectDeviceKind(PortDeviceKind.PATCH_PANEL);
            form.group.patchValue({ syntax: 'P{n}-F' });

            expect(form.isPatchPanel).toBeTrue();
            expect(form.isStepValid(1)).toBeFalse();

            form.group.patchValue({ rearSyntax: 'P{n}-R' });

            expect(form.isStepValid(1)).toBeTrue();
        });

        it('refuses the same name on both faces', () => {
            form.selectDeviceKind(PortDeviceKind.PATCH_PANEL);
            form.group.patchValue({ syntax: 'P{n}', rearSyntax: 'P{n}' });
            form.revalidateRearSyntax();
            form.group.controls.rearSyntax.markAsTouched();

            expect(form.group.controls.rearSyntax.hasError('sameSyntax')).toBeTrue();
            expect(form.errorOf('rearSyntax'))
                .toBe('The rear side needs a different name from the front, e.g. -R instead of -F.');
        });

        it('drops the rear name and its rule for a standard device', () => {
            form.selectDeviceKind(PortDeviceKind.PATCH_PANEL);
            form.group.patchValue({ syntax: 'P{n}', rearSyntax: 'P{n}-R' });

            form.selectDeviceKind(PortDeviceKind.STANDARD);

            expect(form.group.controls.rearSyntax.value).toBe('');
            expect(form.isStepValid(1)).toBeTrue();
        });
    });

    describe('step validity', () => {
        it('asks for the device kind first', () => {
            expect(form.isStepValid(0)).toBeFalse();

            form.selectDeviceKind(PortDeviceKind.STANDARD);

            expect(form.isStepValid(0)).toBeTrue();
        });

        it('refuses a name of nothing but spaces', () => {
            form.selectDeviceKind(PortDeviceKind.STANDARD);
            form.group.patchValue({ syntax: '   ' });

            expect(form.isStepValid(1)).toBeFalse();
        });

        it('refuses a count below one', () => {
            form.group.patchValue({ count: '0' });

            expect(form.isStepValid(2)).toBeFalse();
            form.markStepTouched(2);
            expect(form.errorOf('count')).toBe('Please enter a whole number of at least 1.');
        });

        it('accepts a start index of zero', () => {
            form.group.patchValue({ startIndex: '0' });

            expect(form.isStepValid(2)).toBeTrue();
        });

        it('holds no message before the user has left the field', () => {
            form.group.patchValue({ count: 'x' });

            expect(form.errorOf('count')).toBe('');
        });
    });

    describe('request bodies', () => {
        beforeEach(() => {
            form.selectDeviceKind(PortDeviceKind.STANDARD);
            form.group.patchValue({ syntax: '  Gi0/{n}  ', count: ' 24 ', startIndex: '1' });
        });

        it('trims the naming keys and leaves out the empty optional ones', () => {
            expect(form.toNamingRequest(PortDeviceKind.STANDARD)).toEqual({
                device_kind: PortDeviceKind.STANDARD,
                syntax: 'Gi0/{n}',
                count: 24,
                start_index: 1
            });
        });

        it('carries prefix and slot once they are filled in', () => {
            form.group.patchValue({ prefix: 'Gi', slot: '0' });

            expect(form.toNamingRequest(PortDeviceKind.STANDARD)).toEqual({
                device_kind: PortDeviceKind.STANDARD,
                syntax: 'Gi0/{n}',
                count: 24,
                start_index: 1,
                prefix: 'Gi',
                slot: '0'
            });
        });

        it('adds the rear name for a patch panel only', () => {
            form.selectDeviceKind(PortDeviceKind.PATCH_PANEL);
            form.group.patchValue({ rearSyntax: 'P{n}-R' });

            expect(form.toNamingRequest(PortDeviceKind.PATCH_PANEL).rear_syntax).toBe('P{n}-R');
            expect(form.toNamingRequest(PortDeviceKind.STANDARD).rear_syntax).toBeUndefined();
        });

        it('sends untouched selects and an empty description as null', () => {
            expect(form.toBulkRequest(PortDeviceKind.STANDARD)).toEqual({
                device_kind: PortDeviceKind.STANDARD,
                syntax: 'Gi0/{n}',
                count: 24,
                start_index: 1,
                status: null,
                port_type: null,
                speed: null,
                description: null
            });
        });

        it('sends the picked option ids as numbers', () => {
            form.group.patchValue({ status: '7', portType: '10', speed: '23', description: ' Uplink ' });

            const request = form.toBulkRequest(PortDeviceKind.STANDARD);

            expect(request.status).toBe(7);
            expect(request.port_type).toBe(10);
            expect(request.speed).toBe(23);
            expect(request.description).toBe('Uplink');
        });
    });
});
