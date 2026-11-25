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
import { PersonSelection, inactiveSelectorField, personDisplayLabel } from './person-selector';
/* ------------------------------------------------------------------------------------------------------------------ */

function selection(overrides: Partial<PersonSelection> = {}): PersonSelection {
    return {
        object_id: 7,
        type_id: 9801,
        type_label: 'Person',
        kind: 'PERSON',
        label: 'Anna Becker',
        active: true,
        system_ref: null,
        ...overrides
    };
}


describe('person-selector model', () => {

    describe('personDisplayLabel', () => {
        it('uses the label', () => {
            expect(personDisplayLabel(selection())).toBe('Anna Becker');
        });

        it('falls back to the Type and id without a label', () => {
            expect(personDisplayLabel(selection({ label: '  ' }))).toBe('Person #7');
        });

        it('marks a deactivated selection', () => {
            expect(personDisplayLabel(selection({ active: false }))).toBe('Anna Becker (inactive)');
        });
    });


    describe('inactiveSelectorField', () => {
        it('names the field of the INACTIVE refusal', () => {
            const message = "The person selector 'owner' may not newly select deactivated objects: [5, 6]";

            expect(inactiveSelectorField(message)).toBe('owner');
        });

        it('ignores any other refusal', () => {
            expect(inactiveSelectorField("The person selector 'owner' names objects that do not exist: [5]"))
                .toBeNull();
        });

        it('ignores a missing or non-text message', () => {
            expect(inactiveSelectorField(undefined)).toBeNull();
            expect(inactiveSelectorField({ message: 'x' })).toBeNull();
        });
    });
});
