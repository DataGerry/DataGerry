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

* You should have received a copy of the GNU Affero General Public License
* along with this program. If not, see <https://www.gnu.org/licenses/>.
*/
import { safeCssColor } from './color-utils';

/** The allow-list that stands between free-text colour fields and a paint instruction. */
describe('safeCssColor', () => {
    it('accepts a six digit hex literal', () => {
        expect(safeCssColor('#8E44AD')).toBe('#8E44AD');
    });

    it('accepts the short hex form', () => {
        expect(safeCssColor('#abc')).toBe('#abc');
    });

    it('accepts a plain CSS colour name', () => {
        expect(safeCssColor('blue')).toBe('blue');
    });

    it('trims the surrounding whitespace a typed field leaves behind', () => {
        expect(safeCssColor('  blue  ')).toBe('blue');
    });

    it('refuses a url(), which is how a stroke would reach out of the document', () => {
        expect(safeCssColor('url(#evil)')).toBeNull();
    });

    it('refuses a javascript scheme', () => {
        expect(safeCssColor('javascript:alert(1)')).toBeNull();
    });

    it('refuses a functional notation it cannot vouch for', () => {
        expect(safeCssColor('rgb(1, 2, 3)')).toBeNull();
    });

    it('refuses a malformed hex', () => {
        expect(safeCssColor('#12')).toBeNull();
    });

    it('refuses an empty or missing value', () => {
        expect(safeCssColor('')).toBeNull();
        expect(safeCssColor(null)).toBeNull();
        expect(safeCssColor(undefined)).toBeNull();
    });
});
