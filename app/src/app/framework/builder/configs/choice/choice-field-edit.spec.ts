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

import { ComponentFixture, TestBed, fakeAsync, tick, flush } from '@angular/core/testing';
import { NO_ERRORS_SCHEMA } from '@angular/core';
import { FormsModule, ReactiveFormsModule } from '@angular/forms';

import { ChoiceFieldEditComponent } from './choice-field-edit.component';
import { ConfigEditBaseComponent } from '../config.edit';
import { CmdbMode } from '../../../modes.enum';
import { FieldIdentifierValidationService } from 'src/app/framework/builder/services/field-identifier-validation.service';
import { ValidationService } from 'src/app/framework/builder/services/validation.service';

/**
 * Verifies the ngModelChange -> valueChanges migration for the choice field builder.
 * The "required" checkbox intentionally had no (ngModelChange) binding, so it must
 * stay unsubscribed after the migration.
 */

class MockFieldIdentifierValidationService {
    isDuplicate(newValue: string): boolean {
        return false;
    }
}

class MockValidationService {
    setIsValid(identifier: string, isValid: boolean): void { }
    updateFieldValidityOnDeletion(identifier: string): void { }
}

function captureFieldChanges(component: ConfigEditBaseComponent, action: () => void): any[] {
    const events: any[] = [];
    const sub = component.fieldChanges$.subscribe(event => events.push(event));
    action();
    sub.unsubscribe();
    return events;
}

describe('ChoiceFieldEditComponent', () => {
    let component: ChoiceFieldEditComponent;
    let fixture: ComponentFixture<ChoiceFieldEditComponent>;
    let fieldIdentifierValidationService: MockFieldIdentifierValidationService;

    beforeEach(async () => {
        await TestBed.configureTestingModule({
            imports: [ReactiveFormsModule, FormsModule],
            declarations: [ChoiceFieldEditComponent],
            providers: [
                { provide: FieldIdentifierValidationService, useClass: MockFieldIdentifierValidationService },
                { provide: ValidationService, useClass: MockValidationService }
            ],
            schemas: [NO_ERRORS_SCHEMA]
        }).compileComponents();
    });

    beforeEach(() => {
        fixture = TestBed.createComponent(ChoiceFieldEditComponent);
        component = fixture.componentInstance;
        component.data = { label: 'label' };
        fieldIdentifierValidationService = TestBed.inject(FieldIdentifierValidationService);
        component.ngOnInit();
    });

    it('should create the component', () => {
        expect(component).toBeTruthy();
    });

    it('should register every form control on ngOnInit', () => {
        ['required', 'name', 'label', 'description', 'helperText', 'value', 'options', 'hideField']
            .forEach(controlName => expect(component.form.contains(controlName)).toBeTrue());
    });

    it('should seed a default option when none are provided', () => {
        expect(component.options.length).toBeGreaterThan(0);
        expect(component.data.options.length).toBeGreaterThan(0);
    });

    it('should propagate the bound control edits through valueChanges', fakeAsync(() => {
        const cases: Array<{ control: keyof ChoiceFieldEditComponent; type: string; value: string }> = [
            { control: 'labelControl', type: 'label', value: 'Choice' },
            { control: 'descriptionControl', type: 'description', value: 'Pick one' },
            { control: 'helperTextControl', type: 'helperText', value: 'helper' },
            { control: 'valueControl', type: 'value', value: 'option-1' }
        ];

        cases.forEach(({ control, type, value }) => {
            const events = captureFieldChanges(component, () => {
                (component[control] as any).setValue(value);
            });
            const relevant = events.filter(e => e.inputName === type);
            expect(relevant.length).withContext(type).toBe(1);
            expect(relevant[0].newValue).toBe(value);
            expect(relevant[0].elementType).toBe('choise');
        });

        flush();
    }));

    it('should propagate the hideField checkbox through the boolean branch', fakeAsync(() => {
        const handleFieldChangeSpy = spyOn<any>(component, 'handleFieldChange').and.callThrough();

        component.hideFieldControl.setValue(true);

        expect(handleFieldChangeSpy).toHaveBeenCalledWith(true, 'hideField');
        flush();
    }));

    it('should NOT propagate the required checkbox (it had no ngModelChange binding)', fakeAsync(() => {
        const events = captureFieldChanges(component, () => component.requiredControl.setValue(true));

        expect(events.length).toBe(0);
        flush();
    }));

    it('should emit exactly one change when editing a field (toggleFormControls does not cascade)', fakeAsync(() => {
        const events = captureFieldChanges(component, () => component.labelControl.setValue('Only Once'));

        expect(events.length).toBe(1);
        expect(events[0].inputName).toBe('label');
        flush();
    }));

    it('should flag duplicates, disable siblings and emit isDuplicate without a normal change', fakeAsync(() => {
        spyOn(fieldIdentifierValidationService, 'isDuplicate').and.returnValue(true);

        const events = captureFieldChanges(component, () => component.nameControl.setValue('dupe'));

        expect(component.isDuplicate$).toBeTrue();
        expect(events).toContain(jasmine.objectContaining({ isDuplicate: true }));
        expect(events.some(e => e.inputName === 'name')).toBeFalse();
        expect(component.labelControl.disabled).toBeTrue();
        expect(component.optionsControl.disabled).toBeTrue();
        flush();
    }));

    it('should accept a unique name and re-enable siblings', fakeAsync(() => {
        component.labelControl.disable({ emitEvent: false });

        const events = captureFieldChanges(component, () => component.nameControl.setValue('unique_name'));

        expect(component.isDuplicate$).toBeFalse();
        expect(events).toContain(jasmine.objectContaining({ inputName: 'name', newValue: 'unique_name' }));
        expect(component.labelControl.enabled).toBeTrue();
        flush();
    }));

    it('should not emit field changes during initialization', () => {
        const fresh = TestBed.createComponent(ChoiceFieldEditComponent).componentInstance;
        fresh.data = { label: 'Init', name: 'init_name' };
        fresh.hiddenStatus = true;

        const events = captureFieldChanges(fresh, () => fresh.ngOnInit());

        expect(events.length).toBe(0);
        expect(fresh.hideFieldControl.value).toBeTrue();
    });

    it('should stop propagating changes after ngOnDestroy', fakeAsync(() => {
        component.ngOnDestroy();

        const events = captureFieldChanges(component, () => component.labelControl.setValue('After Destroy'));

        expect(events.length).toBe(0);
        flush();
    }));

    it('should disable the name control in edit mode', () => {
        const editComponent = TestBed.createComponent(ChoiceFieldEditComponent).componentInstance;
        editComponent.data = { label: 'label', name: 'existing' };
        editComponent.mode = CmdbMode.Edit;
        editComponent.ngOnInit();

        expect(editComponent.nameControl.disabled).toBeTrue();
    });

    it('should mark validity through ValidationService after the debounce', fakeAsync(() => {
        const validationService = TestBed.inject(ValidationService);
        const setIsValidSpy = spyOn(validationService, 'setIsValid');

        component.labelControl.setValue('validate me');
        expect(setIsValidSpy).not.toHaveBeenCalled();

        tick();
        expect(setIsValidSpy).toHaveBeenCalled();
        flush();
    }));

    /* ------------------------------------ additional migration coverage ------------------------------------ */

    it('should update initialValue when handleFieldChange is called with a new name', () => {
        component['handleFieldChange']('newName', 'name');

        expect(component['initialValue']).toBe(component.nameControl.value);
    });

    it('should accept re-entering the previous value while flagged duplicate', fakeAsync(() => {
        spyOn(fieldIdentifierValidationService, 'isDuplicate').and.returnValue(true);
        component['initialValue'] = 'original';

        component.onInputChange('dupe', 'name');
        expect(component.isDuplicate$).toBeTrue();

        component.onInputChange('original', 'name');
        expect(component.isDuplicate$).toBeFalse();
        expect(component.labelControl.enabled).toBeTrue();
        flush();
    }));

    it('should update initialValue through the reactive name path', fakeAsync(() => {
        component.nameControl.setValue('reactive_name');
        tick();

        expect(component['initialValue']).toBe('reactive_name');
        flush();
    }));

    it('should emit the full field-change contract for a non-name edit', fakeAsync(() => {
        component.nameControl.setValue('host', { emitEvent: false });

        const events = captureFieldChanges(component, () => component.labelControl.setValue('Display'));

        expect(events[0]).toEqual(jasmine.objectContaining({
            newValue: 'Display',
            inputName: 'label',
            fieldName: 'host',
            previousName: component['initialValue'],
            elementType: 'choise'
        }));
        flush();
    }));

    it('should recover from a duplicate once a unique name is entered', fakeAsync(() => {
        const isDuplicateSpy = spyOn(fieldIdentifierValidationService, 'isDuplicate').and.returnValue(true);
        component.nameControl.setValue('dupe');
        expect(component.labelControl.disabled).toBeTrue();

        isDuplicateSpy.and.returnValue(false);
        const events = captureFieldChanges(component, () => component.nameControl.setValue('unique_again'));

        expect(component.isDuplicate$).toBeFalse();
        expect(component.labelControl.enabled).toBeTrue();
        expect(events).toContain(jasmine.objectContaining({ inputName: 'name', newValue: 'unique_again' }));
        flush();
    }));

    it('should stop propagating from every subscribed control after ngOnDestroy', fakeAsync(() => {
        component.ngOnDestroy();

        const events = captureFieldChanges(component, () => {
            component.labelControl.setValue('a');
            component.descriptionControl.setValue('b');
            component.helperTextControl.setValue('c');
            component.valueControl.setValue('d');
            component.hideFieldControl.setValue(true);
        });

        expect(events.length).toBe(0);
        flush();
    }));

    it('should notify ValidationService on destroy when the identifier changed', () => {
        const validationService = TestBed.inject(ValidationService);
        const deletionSpy = spyOn(validationService, 'updateFieldValidityOnDeletion');
        component.nameControl.setValue('renamed', { emitEvent: false });

        component.ngOnDestroy();

        expect(deletionSpy).toHaveBeenCalledWith(component['identifierInitialValue']);
    });
});
