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
* along with this program.  If not, see <https://www.gnu.org/licenses/>.
*/
import { MultiDataSectionEntry } from 'src/app/framework/models/cmdb-object';
/* ------------------------------------------------------------------------------------------------------------------ */

/**
 * Computes the next collision-free multi_data_id for a multi_data_section.
 *
 * A newly added row must never reuse an id that already exists in the section. The backend
 * assigns ids as `highest_id + 1` (so `highest_id` is the last id in use, not a free slot),
 * which means simply reading `highest_id` would clash with the existing top row. Taking the
 * maximum of the counter AND every id currently present, then adding one, guarantees the new
 * id is strictly greater than anything in the section — even if `highest_id` is stale or
 * inconsistent with the stored rows. Unique ids keep edit/delete-by-id and the partial-update
 * diff correct.
 *
 * @param section the section a row is being added to
 * @returns a multi_data_id guaranteed not to collide with any existing row
 */
export function getNextMultiDataId(section: MultiDataSectionEntry | null | undefined): number {
    const usedIds = (section?.values ?? [])
        .map((row) => row?.multi_data_id)
        .filter((id): id is number => typeof id === 'number' && Number.isFinite(id));

    const highest = typeof section?.highest_id === 'number' && Number.isFinite(section.highest_id)
        ? section.highest_id
        : 0;

    return Math.max(highest, ...usedIds, -1) + 1;
}
