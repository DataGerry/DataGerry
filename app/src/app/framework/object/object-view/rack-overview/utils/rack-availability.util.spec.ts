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
import { RackArea, RackRowView } from '../models/rack-overview.types';
import { freeRuns, measureArea, runContaining, slotOptions } from './rack-availability.util';
/* ------------------------------------------------------------------------------------------------------------------ */

/** Only the fields the occupancy maths reads; the rest of a row view is irrelevant here. */
function row(area: RackArea, startSlot: number, height: number, mountId: number): RackRowView {
    return { area, startSlot, height, mountId } as RackRowView;
}


describe('rack availability', () => {

    /** A 42U rack whose front holds U42-U41 and U20, leaving two stretches around them. */
    const rows = [row(RackArea.FRONT, 42, 2, 1), row(RackArea.FRONT, 20, 1, 2)];

    describe('freeRuns', () => {

        it('reports the stretches between the placed rows, top down', () => {
            expect(freeRuns(rows, RackArea.FRONT, 42, null)).toEqual([
                { from: 21, to: 40, size: 20 },
                { from: 1, to: 19, size: 19 }
            ]);
        });


        it('leaves the opposite face untouched', () => {
            expect(freeRuns(rows, RackArea.BACK, 42, null)).toEqual([{ from: 1, to: 42, size: 42 }]);
        });


        it('lets a full depth row block both faces', () => {
            const fullDepth = [row(RackArea.FULL_DEPTH, 10, 2, 3)];
            const expected = [{ from: 11, to: 12, size: 2 }, { from: 1, to: 8, size: 8 }];

            expect(freeRuns(fullDepth, RackArea.FRONT, 12, null)).toEqual(expected);
            expect(freeRuns(fullDepth, RackArea.BACK, 12, null)).toEqual(expected);
        });


        it('checks both faces when the placement itself is full depth', () => {
            const crowded = [row(RackArea.FRONT, 12, 1, 4), row(RackArea.BACK, 1, 1, 5)];

            expect(freeRuns(crowded, RackArea.FULL_DEPTH, 12, null)).toEqual([{ from: 2, to: 11, size: 10 }]);
        });


        it('frees the slots of the row being edited', () => {
            // Dropping the U20 row joins the two stretches below the pair still held at the top.
            expect(freeRuns(rows, RackArea.FRONT, 42, 2)).toEqual([{ from: 1, to: 40, size: 40 }]);

            // Dropping the top pair reopens the head of the rack instead.
            expect(freeRuns(rows, RackArea.FRONT, 42, 1)).toEqual([
                { from: 21, to: 42, size: 22 },
                { from: 1, to: 19, size: 19 }
            ]);
        });


        it('excludes nothing for an id no row carries', () => {
            expect(freeRuns(rows, RackArea.FRONT, 42, 999)).toEqual(freeRuns(rows, RackArea.FRONT, 42, null));
        });


        it('handles a face that is full and one with a single slot left', () => {
            expect(freeRuns([row(RackArea.FRONT, 4, 4, 9)], RackArea.FRONT, 4, null)).toEqual([]);
            expect(freeRuns([row(RackArea.FRONT, 4, 3, 9)], RackArea.FRONT, 4, null))
                .toEqual([{ from: 1, to: 1, size: 1 }]);
        });


        it('reports nothing for areas that carry no slots, or a rack without a height', () => {
            expect(freeRuns(rows, RackArea.LEFT, 42, null)).toEqual([]);
            expect(freeRuns(rows, RackArea.UNASSIGNED, 42, null)).toEqual([]);
            expect(freeRuns(rows, RackArea.FRONT, 0, null)).toEqual([]);
        });
    });


    describe('slotOptions', () => {

        /** The 42U front from the fixture: U42-U41 and U20 are held, everything else is free. */
        const optionsFor = (height: number) => slotOptions(freeRuns(rows, RackArea.FRONT, 42, null), 42, height);

        it('offers every free U as its own placement, top down', () => {
            const options = optionsFor(1);

            expect(options[1]).toEqual({ slot: 40, label: 'U40', disabled: false });
            expect(options[2]).toEqual({ slot: 39, label: 'U39', disabled: false });
            expect(options[options.length - 1]).toEqual({ slot: 1, label: 'U1', disabled: false });
        });


        it('collapses a stretch of taken U into a single disabled entry', () => {
            const options = optionsFor(1);

            // U42 and U41 are held by one row, so they read as the range they cover, not as two lines.
            expect(options[0]).toEqual({ slot: 42, label: 'U42\u2013U41 \u00b7 in use', disabled: true });
            expect(options.filter(option => option.label.includes('in use')))
                .toEqual([
                    { slot: 42, label: 'U42\u2013U41 \u00b7 in use', disabled: true },
                    { slot: 20, label: 'U20 \u00b7 in use', disabled: true }
                ]);
        });


        it('names the range the entered height would take from each anchor', () => {
            expect(optionsFor(3)[1]).toEqual({ slot: 40, label: 'U40\u2013U38', disabled: false });
        });


        it('collapses the tail of a stretch the height outgrows, and keeps it apart from taken U', () => {
            const options = optionsFor(3);
            const start = options.findIndex(option => option.slot === 23);
            const around = options.slice(start, start + 4);

            expect(around).toEqual([
                { slot: 23, label: 'U23\u2013U21', disabled: false },
                { slot: 22, label: 'U22\u2013U21 \u00b7 only 2U free', disabled: true },
                { slot: 20, label: 'U20 \u00b7 in use', disabled: true },
                { slot: 19, label: 'U19\u2013U17', disabled: false }
            ]);
        });


        it('closes a blocked stretch that reaches the bottom of the rack', () => {
            expect(optionsFor(3).pop()).toEqual({ slot: 2, label: 'U2\u2013U1 \u00b7 only 2U free', disabled: true });
        });


        it('treats a missing height as a single U', () => {
            expect(optionsFor(0)).toEqual(optionsFor(1));
        });
    });


    describe('measureArea', () => {

        it('separates the free total from the longest usable stretch', () => {
            expect(measureArea(rows, RackArea.FRONT, 42, null)).toEqual({ free: 39, largestRun: 20 });
        });
    });


    describe('runContaining', () => {

        it('finds the stretch an anchor sits in, and nothing for a taken slot', () => {
            const runs = freeRuns(rows, RackArea.FRONT, 42, null);

            expect(runContaining(runs, 40)).toEqual({ from: 21, to: 40, size: 20 });
            expect(runContaining(runs, 41)).toBeNull();
        });
    });
});
