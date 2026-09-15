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
import { RackApiDate, RackArea, RackMountKind, RackMountRow } from '../models/rack-overview.types';
import { toRowView } from './rack-row-view.util';
import { EXPIRED_ACCENT } from './rack-visual.util';
/* ------------------------------------------------------------------------------------------------------------------ */

const TODAY = '2026-08-26';

const RACK_HEIGHT = 42;

/** Only the fields a drawn row reads; the rest of a backend row is irrelevant here. */
function occupant(kind: RackMountKind, endDate: RackApiDate): RackMountRow {
    return {
        mount_id: 7,
        kind,
        label: 'Migration window',
        area: RackArea.FRONT,
        start_slot: 12,
        height: 2,
        start_date: '2026-08-01',
        end_date: endDate,
        color: '#4caf50'
    } as RackMountRow;
}


describe('rack row view', () => {

    describe('a reservation past its booked period', () => {

        it('is flagged, and says how long it has been holding the slots', () => {
            const view = toRowView(occupant(RackMountKind.RESERVATION, '2026-08-20'), RACK_HEIGHT, TODAY);

            expect(view.isExpired).toBe(true);
            expect(view.expiryNote).toBe('Expired 6 days ago');
        });


        it('is drawn in the alert colour instead of the one it was given', () => {
            const expired = toRowView(occupant(RackMountKind.RESERVATION, '2026-08-20'), RACK_HEIGHT, TODAY);
            const running = toRowView(occupant(RackMountKind.RESERVATION, '2026-09-20'), RACK_HEIGHT, TODAY);

            expect(expired.tone).toBe(EXPIRED_ACCENT);
            expect(running.tone).toBe('#4caf50');
        });


        it('reads as a single day rather than as a count when it ran out yesterday', () => {
            const view = toRowView(occupant(RackMountKind.RESERVATION, '2026-08-25'), RACK_HEIGHT, TODAY);

            expect(view.expiryNote).toBe('Expired since yesterday');
        });


        it('takes the end day the backend reports as a timestamp', () => {
            const view = toRowView(occupant(RackMountKind.RESERVATION, { $date: '2026-08-24T00:00:00Z' }),
                RACK_HEIGHT, TODAY);

            expect(view.isExpired).toBe(true);
        });
    });


    describe('a row that has not run out', () => {

        it('still counts the last booked day itself', () => {
            expect(toRowView(occupant(RackMountKind.RESERVATION, TODAY), RACK_HEIGHT, TODAY).isExpired).toBe(false);
        });


        it('never expires without an end date', () => {
            expect(toRowView(occupant(RackMountKind.RESERVATION, null), RACK_HEIGHT, TODAY).isExpired).toBe(false);
        });


        it('leaves a blocker alone, whatever date it carries', () => {
            const view = toRowView(occupant(RackMountKind.BLOCKER, '2026-08-20'), RACK_HEIGHT, TODAY);

            expect(view.isExpired).toBe(false);
            expect(view.expiryNote).toBeNull();
        });


        it('does not guess at an end the backend did not report as a day', () => {
            expect(toRowView(occupant(RackMountKind.RESERVATION, 'whenever'), RACK_HEIGHT, TODAY).isExpired)
                .toBe(false);
        });
    });
});
