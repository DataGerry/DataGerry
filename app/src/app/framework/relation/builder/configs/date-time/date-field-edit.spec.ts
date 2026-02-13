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

import { ComponentFixture, TestBed } from "@angular/core/testing";
import { DateFieldEditComponent } from "./date-field-edit.component";
import { ReactiveFormsModule, UntypedFormControl } from "@angular/forms";

import { NgbDateAdapter, NgbDateParserFormatter } from "@ng-bootstrap/ng-bootstrap";
import { CustomDateParserFormatter, NgbStringAdapter } from "src/app/settings/date-settings/date-settings-formatter.service";
import { FieldIdentifierValidationService } from "src/app/framework/type/services/field-identifier-validation.service";
import { ValidationService } from "src/app/framework/type/services/validation.service";


class MockFieldIdentifierValidationService {
    isDuplicate(newValue: string): boolean {
        return false;
    }
}

class MockValidationService {
    setIsValid(identifier: string, isValid: boolean) { }
    updateFieldValidityOnDeletion(identifier: string) { }
}

describe('DateFieldEditComponent', () => {
    let component: DateFieldEditComponent;
    let fixture: ComponentFixture<DateFieldEditComponent>;
    let fieldIdentifierValidationService: MockFieldIdentifierValidationService;
    let validationService: MockValidationService;
    let mockData = { label: 'label' };

    beforeEach(async () => {
        await TestBed.configureTestingModule({
            imports: [ReactiveFormsModule],
            declarations: [DateFieldEditComponent],
            providers: [
                { provide: FieldIdentifierValidationService, useClass: MockFieldIdentifierValidationService },
                { provide: ValidationService, useClass: MockValidationService },
                { provide: NgbDateAdapter, useClass: NgbStringAdapter },
                { provide: NgbDateParserFormatter, useClass: CustomDateParserFormatter }
            ]
        }).compileComponents();
    });

    beforeEach(() => {
        fixture = TestBed.createComponent(DateFieldEditComponent);
        component = fixture.componentInstance;
        component.data = mockData;
        fieldIdentifierValidationService = TestBed.inject(FieldIdentifierValidationService);
        validationService = TestBed.inject(ValidationService);

        component.ngOnInit();
        fixture.detectChanges();
    });

    it('should create component', () => {
        expect(component).toBeTruthy();
    });

    it('should initialize form controls on ngOnInit', () => {
        component.ngOnInit();

        expect(component.form.contains('required')).toBe(true);
        expect(component.form.contains('name')).toBe(true);
        expect(component.form.contains('label')).toBe(true);
        expect(component.form.contains('description')).toBe(true);
        expect(component.form.contains('value')).toBe(true);
        expect(component.form.contains('helperText')).toBe(true);
        expect(component.form.contains('hideField')).toBe(true);
    });

    it('should set isDuplicate$ to true when a duplicate name is found', () => {
        spyOn(fieldIdentifierValidationService, 'isDuplicate').and.returnValue(true);

        const event = 'duplicateName';
        const type = 'name';
        component.onInputChange(event, type);

        expect(component.isDuplicate$).toBeTrue();
    });

    it('should handle boolean changes in onInputChange', () => {
        const event = true;
        component.requiredControl.setValue(false);
        component.onInputChange(event, 'required');

        expect(component.requiredControl.value).toBe(event);
    });

    it('should update initialValue when handleFieldChange is called with a new name', () => {
        const newValue = 'newName';
        component['handleFieldChange'](newValue, 'name');

        expect(component['initialValue']).toBe(component.nameControl.value);
    });

    it('should toggle input type to text on double click', () => {
        const event = { target: { type: 'date', select: jasmine.createSpy('select') } } as any;
        component.onDblClick(event as MouseEvent);

        expect(event.target.type).toBe('text');
        expect(event.target.select).toHaveBeenCalled();
    });

    it('should change input type back to date on focus out if type is text', () => {
        const event = { target: { type: 'text' } } as any;
        component.onFocusOut(event as FocusEvent);

        expect(event.target.type).toBe('date');
    });

    it('should reset date when resetDate is called', () => {
        component.valueControl.setValue('2025-01-01');
        component.resetDate();

        expect(component.valueControl.value).toBeUndefined();
        expect(component.data.value).toBeNull();
    });
});
