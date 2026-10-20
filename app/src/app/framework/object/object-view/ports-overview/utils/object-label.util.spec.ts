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
import { RenderResult } from 'src/app/framework/models/cmdb-render';

import { objectDisplayLabel } from './object-label.util';
/* ------------------------------------------------------------------------------------------------------------------ */

function result(overrides: Partial<RenderResult> = {}): RenderResult {
    return {
        object_information: { object_id: 66 },
        summary_line: '',
        type_information: { type_label: '' },
        ...overrides
    } as RenderResult;
}


describe('objectDisplayLabel', () => {
    it('names the object by its summary line', () => {
        expect(objectDisplayLabel(result({ summary_line: 'Switch A' }))).toBe('Switch A #66');
    });

    it('appends the id only where the summary line does not already end in it', () => {
        expect(objectDisplayLabel(result({ summary_line: 'Switch #66' }))).toBe('Switch #66');
    });

    it('falls back to the type label, then to the id alone', () => {
        expect(objectDisplayLabel(result({ type_information: { type_label: 'Router' } as any })))
            .toBe('Router #66');
        expect(objectDisplayLabel(result())).toBe('Object #66');
    });

    it('names the object the caller asked for even when the read answered with nothing', () => {
        expect(objectDisplayLabel(null, 66)).toBe('Object #66');
        expect(objectDisplayLabel(undefined)).toBe('Object');
    });
});
