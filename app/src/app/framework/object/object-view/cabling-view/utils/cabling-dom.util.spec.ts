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
import { cardObjectId } from './cabling-dom.util';

describe('cabling-dom.util', () => {
    it('finds the card an event happened in, from anywhere inside it', () => {
        const card = document.createElement('div');
        const row = document.createElement('span');
        card.dataset['objectId'] = '84';
        card.appendChild(row);

        expect(cardObjectId(row)).toBe(84);
        expect(cardObjectId(card)).toBe(84);
    });

    it('finds nothing outside every card', () => {
        expect(cardObjectId(document.createElement('div'))).toBeNull();
        expect(cardObjectId(null)).toBeNull();
    });
});
