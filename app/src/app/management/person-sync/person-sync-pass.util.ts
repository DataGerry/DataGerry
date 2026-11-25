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
import { SyncPassCounts, SyncPassSummary } from '../models/person-sync';
/* ------------------------------------------------------------------------------------------------------------------ */

const COUNT_LABELS: ReadonlyArray<[keyof SyncPassCounts, string]> = [
    ['created', 'Created'],
    ['edited', 'Edited'],
    ['moved', 'Moved'],
    ['copied', 'Copied']
];


/** The counts a pass answered, in display order; a count it did not send is left out. */
export function summarizeSyncPass(pass: SyncPassCounts): SyncPassSummary {
    const counts = COUNT_LABELS
        .filter(([key]) => typeof pass[key] === 'number')
        .map(([key, label]) => ({ label, value: pass[key] as number }));

    return { counts, left: pass.left ?? [] };
}
