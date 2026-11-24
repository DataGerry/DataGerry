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
import { summarizeSyncPass } from './person-sync-pass.util';
/* ------------------------------------------------------------------------------------------------------------------ */

describe('summarizeSyncPass', () => {

    it('lists every count a settings save answers, in display order', () => {
        const summary = summarizeSyncPass({ created: 2, edited: 0, moved: 1, copied: 0, left: [] });

        expect(summary.counts).toEqual([
            { label: 'Created', value: 2 },
            { label: 'Edited', value: 0 },
            { label: 'Moved', value: 1 },
            { label: 'Copied', value: 0 }
        ]);
    });

    it('leaves out counts the pass did not send', () => {
        expect(summarizeSyncPass({ created: 0, edited: 3 }).counts.map(count => count.label))
            .toEqual(['Created', 'Edited']);
    });

    it('shows only who left when a mapping answers no counts', () => {
        const left = [{ person_group_id: 9821, person_ids: [1] }];
        const summary = summarizeSyncPass({ left });

        expect(summary.counts).toEqual([]);
        expect(summary.left).toEqual(left);
    });

    it('answers an empty left list when none was sent', () => {
        expect(summarizeSyncPass({ created: 1 }).left).toEqual([]);
    });
});
