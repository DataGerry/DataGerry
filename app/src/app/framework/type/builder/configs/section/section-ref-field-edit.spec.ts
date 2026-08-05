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

import { ComponentFixture, TestBed } from '@angular/core/testing';
import { NO_ERRORS_SCHEMA } from '@angular/core';
import { FormsModule, ReactiveFormsModule } from '@angular/forms';
import { of } from 'rxjs';

import { SectionRefFieldEditComponent } from './section-ref-field-edit.component';
import { CmdbMode } from '../../../../modes.enum';
import { TypeService } from '../../../../services/type.service';
import { ToastService } from '../../../../../layout/toast/toast.service';
import { ValidationService } from '../../../services/validation.service';
import { SectionIdentifierService } from '../../../services/SectionIdentifierService.service';

/**
 * The section-reference builder already subscribed to name/label valueChanges, so the
 * removed (ngModelChange) bindings were redundant double-fires. These specs assert the
 * handlers now run exactly once per edit and that duplicate detection still works.
 */

describe('SectionRefFieldEditComponent', () => {
    let component: SectionRefFieldEditComponent;
    let fixture: ComponentFixture<SectionRefFieldEditComponent>;
    let validationService: jasmine.SpyObj<ValidationService>;

    function baseData(): any {
        return { label: 'label', name: 'sec', reference: {}, fields: [] };
    }

    beforeEach(async () => {
        const typeServiceSpy = jasmine.createSpyObj('TypeService', {
            getTypes: of({ results: [], total: 0, pager: { total_pages: 1 } } as any),
            getType: of({ render_meta: { sections: [] } } as any)
        });
        const toastServiceSpy = jasmine.createSpyObj('ToastService', ['error']);
        const validationServiceSpy = jasmine.createSpyObj('ValidationService',
            ['setIsValid', 'setSectionHighlightState', 'updateFieldValidityOnDeletion']);
        const sectionIdentifierSpy = jasmine.createSpyObj('SectionIdentifierService', {
            getActiveIndex: of(0),
            updateSection: true
        });

        await TestBed.configureTestingModule({
            imports: [ReactiveFormsModule, FormsModule],
            declarations: [SectionRefFieldEditComponent],
            providers: [
                { provide: TypeService, useValue: typeServiceSpy },
                { provide: ToastService, useValue: toastServiceSpy },
                { provide: ValidationService, useValue: validationServiceSpy },
                { provide: SectionIdentifierService, useValue: sectionIdentifierSpy }
            ],
            schemas: [NO_ERRORS_SCHEMA]
        }).compileComponents();

        validationService = TestBed.inject(ValidationService) as jasmine.SpyObj<ValidationService>;
    });

    beforeEach(() => {
        fixture = TestBed.createComponent(SectionRefFieldEditComponent);
        component = fixture.componentInstance;
        component.data = baseData();
        component.fields = [];
        component.sections = [];
        // Single ngOnInit so the name/label valueChanges listeners register once.
        component.ngOnInit();
    });

    it('should create the component', () => {
        expect(component).toBeTruthy();
    });

    it('should register the section reference controls on ngOnInit', () => {
        ['name', 'label', 'reference']
            .forEach(controlName => expect(component.form.contains(controlName)).toBeTrue());
    });

    it('should route a name edit through onNameChange exactly once', () => {
        const onNameChangeSpy = spyOn(component, 'onNameChange').and.callThrough();

        component.nameControl.setValue('sectionA');

        expect(onNameChangeSpy).toHaveBeenCalledTimes(1);
        expect(onNameChangeSpy).toHaveBeenCalledWith('sectionA');
    });

    it('should route a label edit through onLabelChange exactly once', () => {
        const onLabelChangeSpy = spyOn(component, 'onLabelChange').and.callThrough();

        component.labelControl.setValue('My Label');

        expect(onLabelChangeSpy).toHaveBeenCalledTimes(1);
        expect(onLabelChangeSpy).toHaveBeenCalledWith('My Label', 'label');
        expect(component.data.label).toBe('My Label');
    });

    it('should emit a non-duplicate change for a unique identifier', () => {
        const events: any[] = [];
        const sub = component.fieldChanges$.subscribe(event => events.push(event));

        component.nameControl.setValue('unique_section');

        sub.unsubscribe();
        expect(events).toContain(jasmine.objectContaining({ isDuplicate: false, elementType: 'ref-section' }));
        expect(component.isIdentifierValid).toBeTrue();
    });

    it('should flag a duplicate identifier and highlight the section', () => {
        component.sections = [{ name: 'taken' } as any];
        const events: any[] = [];
        const sub = component.fieldChanges$.subscribe(event => events.push(event));

        component.nameControl.setValue('taken');

        sub.unsubscribe();
        expect(events).toContain(jasmine.objectContaining({ isDuplicate: true, elementType: 'ref-section' }));
        expect(component.isIdentifierValid).toBeFalse();
        expect(validationService.setSectionHighlightState).toHaveBeenCalledWith(true);
    });

    it('should disable the name control in edit mode', () => {
        const editComponent = TestBed.createComponent(SectionRefFieldEditComponent).componentInstance;
        editComponent.data = baseData();
        editComponent.fields = [];
        editComponent.sections = [];
        editComponent.mode = CmdbMode.Edit;
        editComponent.ngOnInit();

        expect(editComponent.nameControl.disabled).toBeTrue();
    });
});
