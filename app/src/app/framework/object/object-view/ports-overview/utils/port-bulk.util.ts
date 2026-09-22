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
import { PortRow } from '../models/ports-overview.types';
/* ------------------------------------------------------------------------------------------------------------------ */

/**
 * The cables of a selection, each named once.
 *
 * A cable joining two selected ports appears on both rows, and a panel's internal pairing is not a
 * cable at all - neither belongs in a bulk disconnect more than once, or at all.
 */
export function distinctCableConnectionIds(rows: readonly PortRow[]): number[] {
    const ids = new Set<number>();

    for (const row of rows) {
        if (row.cableConnectionId != null) {
            ids.add(row.cableConnectionId);
        }
    }

    return [...ids];
}
