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
import { distinctCableConnectionIds } from './port-bulk.util';
/* ------------------------------------------------------------------------------------------------------------------ */

describe('distinctCableConnectionIds', () => {

    const row = (publicId: number, cableConnectionId: number | null): PortRow =>
        ({ publicId, cableConnectionId } as PortRow);

    it('leaves out the ports that carry no cable', () => {
        expect(distinctCableConnectionIds([row(1, null), row(2, 9720), row(3, null)])).toEqual([9720]);
    });

    it('names a cable joining two selected ports only once', () => {
        expect(distinctCableConnectionIds([row(1, 9720), row(2, 9720), row(3, 9721)])).toEqual([9720, 9721]);
    });

    it('answers an empty selection with an empty list', () => {
        expect(distinctCableConnectionIds([])).toEqual([]);
    });
});
