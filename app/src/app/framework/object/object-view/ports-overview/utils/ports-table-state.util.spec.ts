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
import { Column } from 'src/app/layout/table/table.types';
import { columnsHiddenByState } from './ports-table-state.util';
/* ------------------------------------------------------------------------------------------------------------------ */

describe('columnsHiddenByState', () => {

    const columns: Column[] = [
        { display: 'Port Name', name: 'name', data: 'name', fixed: true },
        { display: 'Port No.', name: 'port_number', data: 'portNumber' },
        { display: 'Speed', name: 'speed', data: 'speed' },
        { display: 'Status', name: 'status', data: 'status' },
        { display: 'Actions', name: 'actions', data: 'publicId', fixed: true }
    ];

    it('hides every column the view does not list', () => {
        const hidden = columnsHiddenByState(columns, { name: 'Compact', visibleColumns: ['name', 'status', 'actions'] });

        expect(hidden).toEqual(['port_number', 'speed']);
    });

    it('never hides a fixed column, even one the view left out', () => {
        const hidden = columnsHiddenByState(columns, { name: 'Compact', visibleColumns: ['speed'] });

        expect(hidden).toEqual(['port_number', 'status']);
    });

    it('hides nothing without a view or with a view that lists no columns', () => {
        expect(columnsHiddenByState(columns, undefined)).toEqual([]);
        expect(columnsHiddenByState(columns, { name: 'Empty', visibleColumns: [] })).toEqual([]);
    });
});
