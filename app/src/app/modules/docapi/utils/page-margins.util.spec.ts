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
import { marginsFitPage, parseMarginValue } from './page-margins.util';

/* ------------------------------------------------------------------------------------------------------------------ */

describe('page-margins.util', () => {
    describe('parseMarginValue', () => {
        it('parses numbers and numeric strings', () => {
            expect(parseMarginValue(12.5)).toBe(12.5);
            expect(parseMarginValue('20')).toBe(20);
            expect(parseMarginValue('0')).toBe(0);
        });

        it('rejects empty, blank and missing values instead of reading them as 0', () => {
            expect(parseMarginValue('')).toBeNull();
            expect(parseMarginValue('   ')).toBeNull();
            expect(parseMarginValue(null)).toBeNull();
            expect(parseMarginValue(undefined)).toBeNull();
        });

        it('rejects negative and non-numeric values', () => {
            expect(parseMarginValue(-1)).toBeNull();
            expect(parseMarginValue('abc')).toBeNull();
        });
    });

    describe('marginsFitPage', () => {
        it('accepts margins that leave a printable area', () => {
            expect(marginsFitPage({ top: 20, bottom: 20, left: 100, right: 100 })).toBeTrue();
        });

        it('rejects horizontal margins that reach the A4 width', () => {
            expect(marginsFitPage({ top: 20, bottom: 20, left: 105, right: 105 })).toBeFalse();
            expect(marginsFitPage({ top: 20, bottom: 20, left: 150, right: 150 })).toBeFalse();
        });

        it('rejects vertical margins that reach the A4 height', () => {
            expect(marginsFitPage({ top: 150, bottom: 147, left: 20, right: 20 })).toBeFalse();
        });
    });
});
