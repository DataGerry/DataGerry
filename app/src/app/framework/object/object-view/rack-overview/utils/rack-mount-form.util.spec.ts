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
import { RackArea, RackMountKind, RackMountRow } from '../models/rack-overview.types';
import {
    RackMountFormValue,
    buildInsertPayload,
    buildUpdatePayload,
    buildValidatePayload,
    toNumber
} from './rack-mount-form.util';
/* ------------------------------------------------------------------------------------------------------------------ */

/** A mount placed in the front area, which is the shape every case below varies from. */
const SLOT_FORM: RackMountFormValue = {
    kind: RackMountKind.MOUNT,
    objectId: 5,
    label: '  Web  ',
    area: RackArea.FRONT,
    // Strings on purpose: this is what a number input hands back.
    startSlot: '38',
    height: '2',
    position: null,
    startDate: null,
    endDate: null,
    color: null
};

/** Only the fields the builders read off the row being edited. */
function existingRow(fields: Partial<RackMountRow>): RackMountRow {
    return fields as RackMountRow;
}


describe('rack mount form', () => {

    describe('toNumber', () => {

        it('reads a number input back, and treats an emptied one as no value', () => {
            expect(toNumber('7')).toBe(7);
            expect(toNumber(0)).toBe(0);
            expect(toNumber('')).toBeNull();
            expect(toNumber('   ')).toBeNull();
            expect(toNumber(null)).toBeNull();
        });
    });


    describe('buildInsertPayload', () => {

        it('sends the slot geometry and trims the label', () => {
            expect(buildInsertPayload(SLOT_FORM)).toEqual({
                area: RackArea.FRONT,
                start_slot: 38,
                height: 2,
                position: null,
                kind: RackMountKind.MOUNT,
                label: 'Web',
                object_id: 5
            });
        });


        it('clears the slot axis for a side area and keeps the ordering', () => {
            const sideForm = { ...SLOT_FORM, area: RackArea.LEFT, position: '3' };

            expect(buildInsertPayload(sideForm)).toEqual({
                area: RackArea.LEFT,
                start_slot: null,
                height: null,
                position: 3,
                kind: RackMountKind.MOUNT,
                label: 'Web',
                object_id: 5
            });
        });


        it('keeps the height as a hint in the tray and omits an empty position', () => {
            const trayForm = { ...SLOT_FORM, area: RackArea.UNASSIGNED, position: '' };

            expect(buildInsertPayload(trayForm)).toEqual({
                area: RackArea.UNASSIGNED,
                start_slot: null,
                height: 2,
                kind: RackMountKind.MOUNT,
                label: 'Web',
                object_id: 5
            });
        });


        it('carries the dates and colour a reservation owns', () => {
            const reservationForm = {
                ...SLOT_FORM,
                kind: RackMountKind.RESERVATION,
                objectId: null,
                startDate: '2026-08-14',
                color: '#4CAF50'
            };

            expect(buildInsertPayload(reservationForm)).toEqual({
                area: RackArea.FRONT,
                start_slot: 38,
                height: 2,
                position: null,
                kind: RackMountKind.RESERVATION,
                label: 'Web',
                start_date: '2026-08-14T00:00:00+00:00',
                end_date: null,
                color: '#4CAF50'
            });
        });


        it('sends no object for a blocker', () => {
            const blockerForm = { ...SLOT_FORM, kind: RackMountKind.BLOCKER, objectId: null };

            expect(buildInsertPayload(blockerForm).object_id).toBeUndefined();
            expect(buildInsertPayload(blockerForm).start_date).toBeUndefined();
        });
    });


    describe('buildValidatePayload', () => {

        it('adds no mount id when a row is being added', () => {
            expect(buildValidatePayload(SLOT_FORM, null).mount_id).toBeUndefined();
        });


        it('names the row being edited so it does not collide with itself', () => {
            const payload = buildValidatePayload(SLOT_FORM, existingRow({ mount_id: 77, object_id: 9 }));

            expect(payload.mount_id).toBe(77);
        });


        it('keeps the object of the row being edited rather than the form value', () => {
            const payload = buildValidatePayload(SLOT_FORM, existingRow({ mount_id: 77, object_id: 9 }));

            expect(payload.object_id).toBe(9);
        });
    });


    describe('buildUpdatePayload', () => {

        it('sends geometry and label only when the row is a mount', () => {
            const existing = existingRow({ mount_id: 77, object_id: 9, kind: RackMountKind.MOUNT });

            expect(buildUpdatePayload(SLOT_FORM, existing)).toEqual({
                area: RackArea.FRONT,
                start_slot: 38,
                height: 2,
                position: null,
                label: 'Web'
            });
        });


        it('adds the reservation fields when the row is a reservation', () => {
            const reservationForm = { ...SLOT_FORM, startDate: '2026-08-14', color: '#4CAF50' };
            const existing = existingRow({ mount_id: 77, kind: RackMountKind.RESERVATION });

            expect(buildUpdatePayload(reservationForm, existing)).toEqual({
                area: RackArea.FRONT,
                start_slot: 38,
                height: 2,
                position: null,
                label: 'Web',
                start_date: '2026-08-14T00:00:00+00:00',
                end_date: null,
                color: '#4CAF50'
            });
        });


        it('clears an emptied label rather than sending a blank string', () => {
            const cleared = { ...SLOT_FORM, label: '   ' };
            const existing = existingRow({ mount_id: 77, kind: RackMountKind.MOUNT });

            expect(buildUpdatePayload(cleared, existing).label).toBeNull();
        });
    });
});
