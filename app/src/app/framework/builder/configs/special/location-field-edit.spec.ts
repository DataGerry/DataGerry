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

import { UntypedFormGroup } from '@angular/forms';

import { LocationFieldEditComponent } from './location-field-edit.component';
import { LocationControl } from '../../controls/specials/location.control';
import { ValidationService } from 'src/app/framework/builder/services/validation.service';
import { CmdbMode } from '../../../modes.enum';

/**
 * The location editor reaches into the palette markup by element id and position before it does
 * anything else, and it seeds its "selectable as location" toggle from the field it is editing.
 * Both were load-bearing enough to leave the editor blank or to silently drop the user's choice.
 */
describe('LocationFieldEditComponent', () => {

    /** Exactly what the palette drops: ngx-drag-drop JSON round-trips every payload. */
    function droppedLocation(): any {
        return JSON.parse(JSON.stringify(new LocationControl().content()));
    }

    function build(data: any, validationService = new ValidationService()) {
        const component = new LocationFieldEditComponent(
            {} as any,
            { error: () => { } } as any,
            { markForCheck: () => { } } as any,
            { snapshot: { data: {} } } as any,
            validationService
        );

        component.data = data;
        component.form = new UntypedFormGroup({});
        component.mode = CmdbMode.Create;

        return component;
    }

    /** The palette markup `setDraggable` expects: #specialControls, with Location second. */
    function renderPalette(itemCount: number): void {
        const group = document.createElement('div');
        group.id = 'specialControls';

        for (let index = 0; index < itemCount; index++) {
            const item = document.createElement('div');
            item.className = 'list-group-item';
            group.appendChild(item);
        }

        document.body.appendChild(group);
    }

    afterEach(() => document.getElementById('specialControls')?.remove());


    describe('initialising against the palette markup', () => {

        it('patches the label when the palette is where it expects', () => {
            renderPalette(2);
            const component = build(droppedLocation());

            component.ngOnInit();

            expect(component.labelControl.value).toBe('Location');
        });


        it('still initialises when the palette is missing entirely', () => {
            const component = build(droppedLocation());

            expect(() => component.ngOnInit()).not.toThrow();
            expect(component.labelControl.value).toBe('Location');
        });


        it('still initialises when the palette holds no second control', () => {
            renderPalette(1);
            const component = build(droppedLocation());

            expect(() => component.ngOnInit()).not.toThrow();
            expect(component.labelControl.value).toBe('Location');
        });


        it('does not throw on destroy when the palette is already gone', () => {
            renderPalette(2);
            const component = build(droppedLocation());
            component.ngOnInit();
            document.getElementById('specialControls')?.remove();

            expect(() => component.ngOnDestroy()).not.toThrow();
        });
    });


    describe('validation state', () => {

        /** Only the builders own the validity maps; one field editor must not reset them. */
        it('leaves the builder-wide validity untouched when destroyed', () => {
            renderPalette(2);
            const validationService = new ValidationService();
            validationService.setIsValid('another_field', false);

            const component = build(droppedLocation(), validationService);
            component.ngOnInit();
            component.ngOnDestroy();

            expect(validationService.fieldValidity.get('another_field')).toBeFalse();
        });
    });


    describe('the selectable-as-location toggle', () => {

        it('seeds itself from the field so a redraw keeps the choice', () => {
            renderPalette(2);
            const data = droppedLocation();
            data.selectable_as_parent = true;

            const component = build(data);
            const emitted: Array<any> = [];
            component.fieldChanges$.subscribe((change: any) => emitted.push(change));
            component.ngOnInit();

            expect(component.selectableAsParentControl.value).toBeTrue();
            expect(emitted.filter(change => change.inputName === 'selectable_as_parent').pop()?.newValue)
                .withContext('a redraw must not push a stale default back over the type')
                .toBeTrue();
        });
    });
});
