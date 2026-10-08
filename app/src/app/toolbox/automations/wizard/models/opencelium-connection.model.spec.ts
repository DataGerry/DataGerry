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
import { OC_METHOD_COLORS, ocMethodColor, ocNextMethodColor } from './opencelium-connection.model';
/* ------------------------------------------------------------------------------------------------------------------ */

describe('method colours', () => {

    /* Saved automations name their calls by these; the first eight must not move. */
    it('hands out the palette first, in its order', () => {
        expect(OC_METHOD_COLORS.map((_color, position) => ocMethodColor(position))).toEqual([...OC_METHOD_COLORS]);
    });


    /* A colour is how a reference names its call; the palette used to start over at the ninth. */
    it('never repeats a colour, however many calls there are', () => {
        const colors = Array.from({ length: 200 }, (_unused, position) => ocMethodColor(position));

        expect(new Set(colors).size).toBe(200);
        colors.forEach(color => expect(color).toMatch(/^#[0-9A-F]{6}$/));
    });


    it('picks the first colour no call uses yet', () => {
        const methods = OC_METHOD_COLORS.map(color => ({ color }));

        expect(ocNextMethodColor([])).toBe(OC_METHOD_COLORS[0]);
        expect(ocNextMethodColor(methods.slice(0, 3))).toBe(OC_METHOD_COLORS[3]);
        expect(ocNextMethodColor(methods)).toBe(ocMethodColor(8));
        expect(OC_METHOD_COLORS).not.toContain(ocNextMethodColor(methods));
        expect(ocNextMethodColor([{ color: '#ffcfb5' }])).toBe(OC_METHOD_COLORS[1]);
    });
});
