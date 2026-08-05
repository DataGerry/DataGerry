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
* along with this program.  If not, see <https://www.gnu.org/licenses/>.
*/
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { NO_ERRORS_SCHEMA } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { SelectComponent } from './select.component';

interface TestItem {
    public_id: number;
    display_name: string;
    disabled?: boolean;
}

describe('SelectComponent (app-form-select)', () => {
    let component: SelectComponent;
    let fixture: ComponentFixture<SelectComponent>;

    const sampleItems: TestItem[] = [
        { public_id: 1, display_name: 'Alpha' },
        { public_id: 2, display_name: 'Beta' },
        { public_id: 3, display_name: 'Gamma' }
    ];

    beforeEach(async () => {
        await TestBed.configureTestingModule({
            declarations: [SelectComponent],
            imports: [FormsModule],
            schemas: [NO_ERRORS_SCHEMA]
        }).compileComponents();

        fixture = TestBed.createComponent(SelectComponent);
        component = fixture.componentInstance;
    });

    // -------------------------------------------------------------------------
    // Creation & defaults
    // -------------------------------------------------------------------------
    describe('creation', () => {
        it('should create the component', () => {
            expect(component).toBeTruthy();
        });

        it('should expose sensible defaults', () => {
            expect(component.label).toBe('');
            expect(component.items).toEqual([]);
            expect(component.bindLabel).toBe('name');
            expect(component.bindValue).toBe('public_id');
            expect(component.placeholder).toBe('Select...');
            expect(component.multiple).toBeFalse();
            expect(component.required).toBeFalse();
            expect(component.disabled).toBeFalse();
            expect(component.enableSelectAll).toBeFalse();
            expect(component.dropdownDirection).toBe('bottom');
            expect(component.value).toBeNull();
        });

        it('ngOnInit should not throw', () => {
            expect(() => component.ngOnInit()).not.toThrow();
        });
    });

    // -------------------------------------------------------------------------
    // ControlValueAccessor contract
    // -------------------------------------------------------------------------
    describe('ControlValueAccessor', () => {
        it('writeValue should update the internal value (scalar)', () => {
            component.writeValue(42);
            expect(component.value).toBe(42);
        });

        it('writeValue should update the internal value (array)', () => {
            component.writeValue([1, 2, 3]);
            expect(component.value).toEqual([1, 2, 3]);
        });

        it('writeValue should accept null', () => {
            component.value = 5;
            component.writeValue(null);
            expect(component.value).toBeNull();
        });

        it('registerOnChange should store the callback and use it on value changes', () => {
            const onChangeSpy = jasmine.createSpy('onChange');
            component.registerOnChange(onChangeSpy);
            component.items = sampleItems;
            component.onValueChange(sampleItems[0]);
            expect(onChangeSpy).toHaveBeenCalledWith(1);
        });

        it('registerOnTouched should store the callback and use it on value changes', () => {
            const onTouchedSpy = jasmine.createSpy('onTouched');
            component.registerOnTouched(onTouchedSpy);
            component.onValueChange(sampleItems[0]);
            expect(onTouchedSpy).toHaveBeenCalled();
        });

        it('setDisabledState should toggle the disabled flag', () => {
            component.setDisabledState(true);
            expect(component.disabled).toBeTrue();
            component.setDisabledState(false);
            expect(component.disabled).toBeFalse();
        });
    });

    // -------------------------------------------------------------------------
    // onValueChange — single mode
    // -------------------------------------------------------------------------
    describe('onValueChange — single selection', () => {
        beforeEach(() => {
            component.multiple = false;
            component.items = sampleItems;
        });

        it('should set value to item[bindValue] when an item is selected', () => {
            component.onValueChange(sampleItems[1]);
            expect(component.value).toBe(2);
        });

        it('should set value to null when selectedValue is null', () => {
            component.value = 1;
            component.onValueChange(null);
            expect(component.value).toBeNull();
        });

        it('should set value to null when selectedValue is undefined', () => {
            component.value = 1;
            component.onValueChange(undefined);
            expect(component.value).toBeNull();
        });

        it('should respect a custom bindValue', () => {
            component.bindValue = 'display_name';
            component.onValueChange(sampleItems[0]);
            expect(component.value).toBe('Alpha');
        });

        it('should emit selectedItemChange with the original item', () => {
            const spy = spyOn(component.selectedItemChange, 'emit');
            component.onValueChange(sampleItems[2]);
            expect(spy).toHaveBeenCalledWith(sampleItems[2]);
        });

        it('should emit null through selectedItemChange when cleared', () => {
            const spy = spyOn(component.selectedItemChange, 'emit');
            component.onValueChange(null);
            expect(spy).toHaveBeenCalledWith(null);
        });
    });

    // -------------------------------------------------------------------------
    // onValueChange — multiple mode
    // -------------------------------------------------------------------------
    describe('onValueChange — multiple selection', () => {
        beforeEach(() => {
            component.multiple = true;
            component.items = sampleItems;
        });

        it('should map selected items to an array of bind values', () => {
            component.onValueChange([sampleItems[0], sampleItems[2]]);
            expect(component.value).toEqual([1, 3]);
        });

        it('should set value to an empty array when selectedValue is an empty array', () => {
            component.value = [1, 2];
            component.onValueChange([]);
            expect(component.value).toEqual([]);
        });

        it('should set value to an empty array when selectedValue is null (defensive)', () => {
            component.value = [1, 2];
            component.onValueChange(null);
            expect(component.value).toEqual([]);
        });

        it('should set value to an empty array when selectedValue is undefined (defensive)', () => {
            component.value = [1, 2];
            component.onValueChange(undefined);
            expect(component.value).toEqual([]);
        });

        it('should respect a custom bindValue', () => {
            component.bindValue = 'display_name';
            component.onValueChange([sampleItems[0], sampleItems[1]]);
            expect(component.value).toEqual(['Alpha', 'Beta']);
        });

        it('should emit selectedItemChange with the raw items array', () => {
            const spy = spyOn(component.selectedItemChange, 'emit');
            const payload = [sampleItems[0], sampleItems[1]];
            component.onValueChange(payload);
            expect(spy).toHaveBeenCalledWith(payload);
        });

        it('should emit an empty array through selectedItemChange when cleared with null', () => {
            const spy = spyOn(component.selectedItemChange, 'emit');
            component.onValueChange(null);
            expect(spy).toHaveBeenCalledWith([]);
        });

        it('should notify the registered onChange callback with the mapped bind values', () => {
            const onChangeSpy = jasmine.createSpy('onChange');
            component.registerOnChange(onChangeSpy);
            component.onValueChange([sampleItems[1], sampleItems[2]]);
            expect(onChangeSpy).toHaveBeenCalledWith([2, 3]);
        });
    });

    // -------------------------------------------------------------------------
    // selectableItems getter
    // -------------------------------------------------------------------------
    describe('selectableItems', () => {
        it('should return all items when none are disabled', () => {
            component.items = sampleItems;
            expect(component.selectableItems).toEqual(sampleItems);
        });

        it('should filter out items flagged as disabled', () => {
            component.items = [
                { public_id: 1, display_name: 'Alpha' },
                { public_id: 2, display_name: 'Beta', disabled: true },
                { public_id: 3, display_name: 'Gamma' }
            ];
            const ids = component.selectableItems.map(i => i.public_id);
            expect(ids).toEqual([1, 3]);
        });

        it('should return an empty array when items is null or undefined', () => {
            component.items = null as any;
            expect(component.selectableItems).toEqual([]);
            component.items = undefined as any;
            expect(component.selectableItems).toEqual([]);
        });

        it('should treat falsy disabled values as selectable', () => {
            component.items = [
                { public_id: 1, display_name: 'Alpha', disabled: false },
                { public_id: 2, display_name: 'Beta' }
            ];
            expect(component.selectableItems.length).toBe(2);
        });
    });

    // -------------------------------------------------------------------------
    // showSelectAllToggle getter
    // -------------------------------------------------------------------------
    describe('showSelectAllToggle', () => {
        beforeEach(() => {
            component.multiple = true;
            component.enableSelectAll = true;
            component.disabled = false;
            component.items = sampleItems;
        });

        it('should be true when all conditions are met', () => {
            expect(component.showSelectAllToggle).toBeTrue();
        });

        it('should be false when multiple is false', () => {
            component.multiple = false;
            expect(component.showSelectAllToggle).toBeFalse();
        });

        it('should be false when enableSelectAll is false', () => {
            component.enableSelectAll = false;
            expect(component.showSelectAllToggle).toBeFalse();
        });

        it('should be false when the component is disabled', () => {
            component.disabled = true;
            expect(component.showSelectAllToggle).toBeFalse();
        });

        it('should be false when items is empty', () => {
            component.items = [];
            expect(component.showSelectAllToggle).toBeFalse();
        });

        it('should be false when every item is disabled', () => {
            component.items = [
                { public_id: 1, display_name: 'Alpha', disabled: true },
                { public_id: 2, display_name: 'Beta', disabled: true }
            ];
            expect(component.showSelectAllToggle).toBeFalse();
        });
    });

    // -------------------------------------------------------------------------
    // allSelectableSelected getter
    // -------------------------------------------------------------------------
    describe('allSelectableSelected', () => {
        beforeEach(() => {
            component.multiple = true;
            component.items = sampleItems;
        });

        it('should be false when value is null', () => {
            component.value = null;
            expect(component.allSelectableSelected).toBeFalse();
        });

        it('should be false when value is an empty array', () => {
            component.value = [];
            expect(component.allSelectableSelected).toBeFalse();
        });

        it('should be false when only some selectable items are selected', () => {
            component.value = [1, 2];
            expect(component.allSelectableSelected).toBeFalse();
        });

        it('should be true when every selectable item is selected', () => {
            component.value = [1, 2, 3];
            expect(component.allSelectableSelected).toBeTrue();
        });

        it('should ignore disabled items when checking', () => {
            component.items = [
                { public_id: 1, display_name: 'Alpha' },
                { public_id: 2, display_name: 'Beta', disabled: true },
                { public_id: 3, display_name: 'Gamma' }
            ];
            component.value = [1, 3];
            expect(component.allSelectableSelected).toBeTrue();
        });

        it('should be false when there are no selectable items', () => {
            component.items = [];
            component.value = [];
            expect(component.allSelectableSelected).toBeFalse();
        });

        it('should respect a custom bindValue', () => {
            component.bindValue = 'display_name';
            component.value = ['Alpha', 'Beta', 'Gamma'];
            expect(component.allSelectableSelected).toBeTrue();
        });

        it('should not be confused by extra unrelated values in `value`', () => {
            component.value = [1, 2, 3, 999];
            expect(component.allSelectableSelected).toBeTrue();
        });
    });

    // -------------------------------------------------------------------------
    // toggleSelectAll
    // -------------------------------------------------------------------------
    describe('toggleSelectAll', () => {
        beforeEach(() => {
            component.multiple = true;
            component.enableSelectAll = true;
            component.items = sampleItems;
            component.value = [];
        });

        it('should select all selectable items when none are selected', () => {
            component.toggleSelectAll();
            expect(component.value).toEqual([1, 2, 3]);
        });

        it('should select all selectable items when some are selected', () => {
            component.value = [1];
            component.toggleSelectAll();
            expect(component.value).toEqual([1, 2, 3]);
        });

        it('should clear the selection when all are already selected', () => {
            component.value = [1, 2, 3];
            component.toggleSelectAll();
            expect(component.value).toEqual([]);
        });

        it('should not select disabled items', () => {
            component.items = [
                { public_id: 1, display_name: 'Alpha' },
                { public_id: 2, display_name: 'Beta', disabled: true },
                { public_id: 3, display_name: 'Gamma' }
            ];
            component.toggleSelectAll();
            expect(component.value).toEqual([1, 3]);
        });

        it('should emit selectedItemChange with the resulting items', () => {
            const spy = spyOn(component.selectedItemChange, 'emit');
            component.toggleSelectAll();
            expect(spy).toHaveBeenCalledWith(sampleItems);
        });

        it('should emit an empty array through selectedItemChange when deselecting all', () => {
            component.value = [1, 2, 3];
            const spy = spyOn(component.selectedItemChange, 'emit');
            component.toggleSelectAll();
            expect(spy).toHaveBeenCalledWith([]);
        });

        it('should notify the registered onChange callback', () => {
            const onChangeSpy = jasmine.createSpy('onChange');
            component.registerOnChange(onChangeSpy);
            component.toggleSelectAll();
            expect(onChangeSpy).toHaveBeenCalledWith([1, 2, 3]);
        });

        it('should call the registered onTouched callback', () => {
            const onTouchedSpy = jasmine.createSpy('onTouched');
            component.registerOnTouched(onTouchedSpy);
            component.toggleSelectAll();
            expect(onTouchedSpy).toHaveBeenCalled();
        });

        it('should be a no-op when multiple is false', () => {
            component.multiple = false;
            component.value = null;
            component.toggleSelectAll();
            expect(component.value).toBeNull();
        });

        it('should be a no-op when enableSelectAll is false', () => {
            component.enableSelectAll = false;
            component.toggleSelectAll();
            expect(component.value).toEqual([]);
        });

        it('should be a no-op when the component is disabled', () => {
            component.disabled = true;
            component.toggleSelectAll();
            expect(component.value).toEqual([]);
        });

        it('should be a no-op when there are no selectable items', () => {
            component.items = [];
            component.toggleSelectAll();
            expect(component.value).toEqual([]);
        });

        it('should use the configured bindValue when collecting selected values', () => {
            component.bindValue = 'display_name';
            component.value = [];
            component.toggleSelectAll();
            expect(component.value).toEqual(['Alpha', 'Beta', 'Gamma']);
        });
    });

    // -------------------------------------------------------------------------
    // hasSelection getter
    // Drives the enabled state of the standalone "Deselect All" action.
    // -------------------------------------------------------------------------
    describe('hasSelection', () => {
        beforeEach(() => {
            component.multiple = true;
            component.items = sampleItems;
        });

        it('should be false when value is null', () => {
            component.value = null;
            expect(component.hasSelection).toBeFalse();
        });

        it('should be false when value is undefined', () => {
            component.value = undefined;
            expect(component.hasSelection).toBeFalse();
        });

        it('should be false when value is an empty array', () => {
            component.value = [];
            expect(component.hasSelection).toBeFalse();
        });

        it('should be true when exactly one selectable item is selected', () => {
            component.value = [2];
            expect(component.hasSelection).toBeTrue();
        });

        it('should be true when some selectable items are selected', () => {
            component.value = [1, 3];
            expect(component.hasSelection).toBeTrue();
        });

        it('should be true when every selectable item is selected', () => {
            component.value = [1, 2, 3];
            expect(component.hasSelection).toBeTrue();
        });

        it('should be false when there are no selectable items', () => {
            component.items = [];
            component.value = [];
            expect(component.hasSelection).toBeFalse();
        });

        it('should ignore selected values that map only to disabled items', () => {
            component.items = [
                { public_id: 1, display_name: 'Alpha' },
                { public_id: 2, display_name: 'Beta', disabled: true }
            ];
            component.value = [2];
            expect(component.hasSelection).toBeFalse();
        });

        it('should be true when a selectable item is selected alongside a disabled one', () => {
            component.items = [
                { public_id: 1, display_name: 'Alpha' },
                { public_id: 2, display_name: 'Beta', disabled: true }
            ];
            component.value = [1, 2];
            expect(component.hasSelection).toBeTrue();
        });

        it('should not be confused by extra unrelated values in `value`', () => {
            component.value = [999];
            expect(component.hasSelection).toBeFalse();
        });

        it('should respect a custom bindValue', () => {
            component.bindValue = 'display_name';
            component.value = ['Beta'];
            expect(component.hasSelection).toBeTrue();
        });
    });

    // -------------------------------------------------------------------------
    // selectAll
    // -------------------------------------------------------------------------
    describe('selectAll', () => {
        beforeEach(() => {
            component.multiple = true;
            component.enableSelectAll = true;
            component.items = sampleItems;
            component.value = [];
        });

        it('should select every selectable item when none are selected', () => {
            component.selectAll();
            expect(component.value).toEqual([1, 2, 3]);
        });

        it('should select every selectable item from a partial selection', () => {
            component.value = [2];
            component.selectAll();
            expect(component.value).toEqual([1, 2, 3]);
        });

        it('should not include disabled items', () => {
            component.items = [
                { public_id: 1, display_name: 'Alpha' },
                { public_id: 2, display_name: 'Beta', disabled: true },
                { public_id: 3, display_name: 'Gamma' }
            ];
            component.selectAll();
            expect(component.value).toEqual([1, 3]);
        });

        it('should emit selectedItemChange with the resulting items', () => {
            const spy = spyOn(component.selectedItemChange, 'emit');
            component.selectAll();
            expect(spy).toHaveBeenCalledWith(sampleItems);
        });

        it('should notify the registered onChange callback', () => {
            const onChangeSpy = jasmine.createSpy('onChange');
            component.registerOnChange(onChangeSpy);
            component.selectAll();
            expect(onChangeSpy).toHaveBeenCalledWith([1, 2, 3]);
        });

        it('should call the registered onTouched callback', () => {
            const onTouchedSpy = jasmine.createSpy('onTouched');
            component.registerOnTouched(onTouchedSpy);
            component.selectAll();
            expect(onTouchedSpy).toHaveBeenCalled();
        });

        it('should be a no-op when everything is already selected', () => {
            component.value = [1, 2, 3];
            const spy = spyOn(component.selectedItemChange, 'emit');
            component.selectAll();
            expect(component.value).toEqual([1, 2, 3]);
            expect(spy).not.toHaveBeenCalled();
        });

        it('should be a no-op when multiple is false', () => {
            component.multiple = false;
            component.value = null;
            component.selectAll();
            expect(component.value).toBeNull();
        });

        it('should be a no-op when enableSelectAll is false', () => {
            component.enableSelectAll = false;
            component.selectAll();
            expect(component.value).toEqual([]);
        });

        it('should be a no-op when the component is disabled', () => {
            component.disabled = true;
            component.selectAll();
            expect(component.value).toEqual([]);
        });

        it('should be a no-op when there are no selectable items', () => {
            component.items = [];
            component.selectAll();
            expect(component.value).toEqual([]);
        });

        it('should use the configured bindValue when collecting selected values', () => {
            component.bindValue = 'display_name';
            component.selectAll();
            expect(component.value).toEqual(['Alpha', 'Beta', 'Gamma']);
        });
    });

    // -------------------------------------------------------------------------
    // deselectAll
    // -------------------------------------------------------------------------
    describe('deselectAll', () => {
        beforeEach(() => {
            component.multiple = true;
            component.enableSelectAll = true;
            component.items = sampleItems;
            component.value = [1, 2, 3];
        });

        it('should clear a full selection', () => {
            component.deselectAll();
            expect(component.value).toEqual([]);
        });

        it('should clear a partial selection (single item)', () => {
            component.value = [2];
            component.deselectAll();
            expect(component.value).toEqual([]);
        });

        it('should clear a partial selection (multiple items)', () => {
            component.value = [1, 3];
            component.deselectAll();
            expect(component.value).toEqual([]);
        });

        it('should emit an empty array through selectedItemChange', () => {
            const spy = spyOn(component.selectedItemChange, 'emit');
            component.deselectAll();
            expect(spy).toHaveBeenCalledWith([]);
        });

        it('should notify the registered onChange callback with an empty array', () => {
            const onChangeSpy = jasmine.createSpy('onChange');
            component.registerOnChange(onChangeSpy);
            component.deselectAll();
            expect(onChangeSpy).toHaveBeenCalledWith([]);
        });

        it('should call the registered onTouched callback', () => {
            const onTouchedSpy = jasmine.createSpy('onTouched');
            component.registerOnTouched(onTouchedSpy);
            component.deselectAll();
            expect(onTouchedSpy).toHaveBeenCalled();
        });

        it('should be a no-op when nothing is selected', () => {
            component.value = [];
            const spy = spyOn(component.selectedItemChange, 'emit');
            component.deselectAll();
            expect(component.value).toEqual([]);
            expect(spy).not.toHaveBeenCalled();
        });

        it('should be a no-op when only disabled items are selected', () => {
            component.items = [
                { public_id: 1, display_name: 'Alpha' },
                { public_id: 2, display_name: 'Beta', disabled: true }
            ];
            component.value = [2];
            const spy = spyOn(component.selectedItemChange, 'emit');
            component.deselectAll();
            expect(component.value).toEqual([2]);
            expect(spy).not.toHaveBeenCalled();
        });

        it('should be a no-op when multiple is false', () => {
            component.multiple = false;
            component.value = 1;
            component.deselectAll();
            expect(component.value).toBe(1);
        });

        it('should be a no-op when enableSelectAll is false', () => {
            component.enableSelectAll = false;
            component.deselectAll();
            expect(component.value).toEqual([1, 2, 3]);
        });

        it('should be a no-op when the component is disabled', () => {
            component.disabled = true;
            component.deselectAll();
            expect(component.value).toEqual([1, 2, 3]);
        });
    });

    // -------------------------------------------------------------------------
    // Partial-selection UX: Select All and Deselect All are independent.
    // This is the core behavior the standalone buttons rely on — both actions
    // must be usable at the same time when the selection is partial.
    // -------------------------------------------------------------------------
    describe('partial-selection independence', () => {
        beforeEach(() => {
            component.multiple = true;
            component.enableSelectAll = true;
            component.items = sampleItems;
        });

        it('with a partial selection, both actions are enabled and effective', () => {
            component.value = [2];

            // "Select All" enabled (not everything selected yet)
            expect(component.allSelectableSelected).toBeFalse();
            // "Deselect All" enabled (something is selected)
            expect(component.hasSelection).toBeTrue();

            component.selectAll();
            expect(component.value).toEqual([1, 2, 3]);
        });

        it('from a partial selection, deselectAll clears in one step', () => {
            component.value = [1, 2];
            component.deselectAll();
            expect(component.value).toEqual([]);
            expect(component.hasSelection).toBeFalse();
        });

        it('with nothing selected, only Select All applies', () => {
            component.value = [];
            expect(component.allSelectableSelected).toBeFalse();
            expect(component.hasSelection).toBeFalse();
        });

        it('with everything selected, only Deselect All applies', () => {
            component.value = [1, 2, 3];
            expect(component.allSelectableSelected).toBeTrue();
            expect(component.hasSelection).toBeTrue();
        });

        it('selectAll then deselectAll returns to an empty selection', () => {
            component.value = [];
            component.selectAll();
            expect(component.value).toEqual([1, 2, 3]);
            component.deselectAll();
            expect(component.value).toEqual([]);
        });
    });

    // -------------------------------------------------------------------------
    // Integration: writeValue → allSelectableSelected → toggleSelectAll
    // Simulates the round-trip a reactive form would drive through the CVA.
    // -------------------------------------------------------------------------
    describe('integration with reactive forms (round-trip)', () => {
        beforeEach(() => {
            component.multiple = true;
            component.enableSelectAll = true;
            component.items = sampleItems;
        });

        it('writeValue([1,2,3]) should mark allSelectableSelected as true', () => {
            component.writeValue([1, 2, 3]);
            expect(component.allSelectableSelected).toBeTrue();
        });

        it('writeValue([1]) followed by toggleSelectAll should select everything and notify forms', () => {
            const onChangeSpy = jasmine.createSpy('onChange');
            component.registerOnChange(onChangeSpy);
            component.writeValue([1]);
            component.toggleSelectAll();
            expect(component.value).toEqual([1, 2, 3]);
            expect(onChangeSpy).toHaveBeenCalledWith([1, 2, 3]);
        });

        it('writeValue([1,2,3]) followed by toggleSelectAll should clear and notify forms', () => {
            const onChangeSpy = jasmine.createSpy('onChange');
            component.registerOnChange(onChangeSpy);
            component.writeValue([1, 2, 3]);
            component.toggleSelectAll();
            expect(component.value).toEqual([]);
            expect(onChangeSpy).toHaveBeenCalledWith([]);
        });
    });
});
