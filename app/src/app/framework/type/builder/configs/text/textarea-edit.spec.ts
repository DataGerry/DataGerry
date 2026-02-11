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
import { TextareaEditComponent } from "./textarea-edit.component"
import { ReactiveFormsModule } from "@angular/forms";
import { FieldIdentifierValidationService } from "../../../services/field-identifier-validation.service";



class MockFieldIdentifierValidationService {
    isDuplicate(newValue: string): boolean {
        return false;
    }
}

describe('TextareaEditComponent', () => {
    let component: TextareaEditComponent;
    let fixture: ComponentFixture<TextareaEditComponent>;
    let fieldIdentifierValidationService: MockFieldIdentifierValidationService
    let mockData = { label: 'label' }

    beforeEach(async () => {
        await TestBed.configureTestingModule({
            imports: [ReactiveFormsModule],
            declarations: [TextareaEditComponent],
            providers: [{
                provide: FieldIdentifierValidationService,
                useClass: MockFieldIdentifierValidationService
            }]
        }).compileComponents();
    });

    beforeEach(() => {
        fixture = TestBed.createComponent(TextareaEditComponent);
        component = fixture.componentInstance;
        component.data = mockData;
        fieldIdentifierValidationService = TestBed.inject(FieldIdentifierValidationService);

        component.ngOnInit();
        fixture.detectChanges();
    });

    it('should create component', () => {

        expect(component).toBeTruthy();
    });

    it('should initialize form controls on ngOninit', () => {
        component.ngOnInit()

        expect(component.form.contains('required')).toBe(true);
        expect(component.form.contains('name')).toBe(true);
        expect(component.form.contains('label')).toBe(true);
        expect(component.form.contains('description')).toBe(true);
        expect(component.form.contains('rows')).toBe(true);
        expect(component.form.contains('placeholder')).toBe(true);
        expect(component.form.contains('value')).toBe(true);
        expect(component.form.contains('helperText')).toBe(true);
        expect(component.form.contains('hideField')).toBe(true);
    });

    it('should handle boolean changes in onInputChange', () => {
        const event = true;
        component.requiredControl.setValue(false);  // Ensure initial value is different
        component.requiredControl.setValue(event);

        expect(component.requiredControl.value).toBe(event);

    })


    it('should set isDuplicate$ to true when a duplicate name is found', () => {
        spyOn(fieldIdentifierValidationService, 'isDuplicate').and.returnValue(true);

        const event = 'duplicateName';
        const type = 'name';
        component.onInputChange(event, type);

        expect(component.isDuplicate$).toBeTrue();
    });


    it('should update initialValue when handleFieldChange is called with a new name', () => {
        const newValue = 'newName';
        component['handleFieldChange'](newValue, 'name');

        expect(component['initialValue']).toBe(component.nameControl.value);
    });
})