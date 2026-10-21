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
import { Column, TableState } from 'src/app/layout/table/table.types';
/* ------------------------------------------------------------------------------------------------------------------ */

/** The columns a saved view leaves out. A fixed column always shows, and a view without columns hides none. */
export function columnsHiddenByState(columns: readonly Column[], state: TableState | undefined): string[] {
    const visible = state?.visibleColumns;

    if (!visible?.length) {
        return [];
    }

    return columns
        .filter((column) => !column.fixed && !visible.includes(column.name))
        .map((column) => column.name);
}
