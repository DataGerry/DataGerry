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

import { ComponentFixture, TestBed, fakeAsync, flush } from '@angular/core/testing';
import { NO_ERRORS_SCHEMA } from '@angular/core';
import { FormsModule, ReactiveFormsModule } from '@angular/forms';
import { of } from 'rxjs';

import { RefFieldEditComponent } from './ref-field-edit.component';
import { CmdbMode } from '../../../modes.enum';
import { nameConvention } from '../../../../layout/directives/name.directive';
import { TypeService } from '../../../services/type.service';
import { ObjectService } from '../../../services/object.service';
import { ToastService } from '../../../../layout/toast/toast.service';
import { ValidationService } from 'src/app/framework/builder/services/validation.service';

/**
 * Verifies the ngModelChange -> valueChanges migration for the reference field builder.
 * Only the name and label inputs were hybrids; the description/helperText/value inputs
 * keep their standalone [(ngModel)] bindings and are out of scope here.
 */

class MockValidationService {
    setIsValid(identifier: string, isValid: boolean): void { }
    updateFieldValidityOnDeletion(identifier: string): void { }
}

describe('RefFieldEditComponent', () => {
    let component: RefFieldEditComponent;
    let fixture: ComponentFixture<RefFieldEditComponent>;

    function buildComponent(data: any, mode: CmdbMode = CmdbMode.Create): RefFieldEditComponent {
        const created = TestBed.createComponent(RefFieldEditComponent).componentInstance;
        created.data = data;
        created.mode = mode;
        created.ngOnInit();
        flush(); // run the init setTimeout(() => onInputChange())
        return created;
    }

    beforeEach(async () => {
        const typeServiceSpy = jasmine.createSpyObj('TypeService', {
            getTypes: of({ results: [], total: 0 } as any)
        });
        const objectServiceSpy = jasmine.createSpyObj('ObjectService', {
            getObjectsByType: of([])
        });
        const toastServiceSpy = jasmine.createSpyObj('ToastService', ['error']);

        await TestBed.configureTestingModule({
            imports: [ReactiveFormsModule, FormsModule],
            declarations: [RefFieldEditComponent],
            providers: [
                { provide: TypeService, useValue: typeServiceSpy },
                { provide: ObjectService, useValue: objectServiceSpy },
                { provide: ToastService, useValue: toastServiceSpy },
                { provide: ValidationService, useClass: MockValidationService }
            ],
            schemas: [NO_ERRORS_SCHEMA]
        }).compileComponents();
    });

    beforeEach(fakeAsync(() => {
        fixture = TestBed.createComponent(RefFieldEditComponent);
        component = fixture.componentInstance;
        component.data = { label: 'label' };
        // Single ngOnInit so listeners are registered once; flush the init timer.
        component.ngOnInit();
        flush();
    }));

    it('should create the component', () => {
        expect(component).toBeTruthy();
    });

    it('should register the reference form controls on ngOnInit', () => {
        ['required', 'name', 'label', 'ref_types', 'summaries']
            .forEach(controlName => expect(component.form.contains(controlName)).toBeTrue());
    });

    /* ---------------------------------------------- name wiring ---------------------------------------------- */

    it('should route name edits through onNameChange', () => {
        const onNameChangeSpy = spyOn(component, 'onNameChange').and.callThrough();

        component.nameControl.setValue('My Ref');

        expect(onNameChangeSpy).toHaveBeenCalledWith('My Ref');
    });

    it('should normalize the field name into data.name', () => {
        component.onNameChange('My Ref');

        expect(component.data.name).toBe(nameConvention('My Ref'));
    });

    /* --------------------------------------------- label wiring --------------------------------------------- */

    it('should route label edits through onInputChange and onRefInputChange', () => {
        const onInputChangeSpy = spyOn(component, 'onInputChange').and.callThrough();
        const onRefInputChangeSpy = spyOn(component, 'onRefInputChange').and.callThrough();

        component.labelControl.setValue('My Label');

        expect(onInputChangeSpy).toHaveBeenCalled();
        expect(onRefInputChangeSpy).toHaveBeenCalledWith('My Label', 'label');
    });

    it('should emit a ref field change payload from onRefInputChange', () => {
        const events: any[] = [];
        const sub = component.fieldChanges$.subscribe(event => events.push(event));

        component.onRefInputChange('a label', 'label');

        sub.unsubscribe();
        expect(events).toContain(jasmine.objectContaining({
            newValue: 'a label',
            inputName: 'label',
            elementType: 'ref'
        }));
    });

    /* -------------------------------------------- lifecycle -------------------------------------------- */

    it('should stop routing name edits after ngOnDestroy', () => {
        component.ngOnDestroy();
        const onNameChangeSpy = spyOn(component, 'onNameChange');

        component.nameControl.setValue('After Destroy');

        expect(onNameChangeSpy).not.toHaveBeenCalled();
    });

    it('should stop routing label edits after ngOnDestroy', () => {
        component.ngOnDestroy();
        const onRefInputChangeSpy = spyOn(component, 'onRefInputChange');

        component.labelControl.setValue('After Destroy');

        expect(onRefInputChangeSpy).not.toHaveBeenCalled();
    });

    it('should disable the name control in edit mode', fakeAsync(() => {
        const editComponent = buildComponent({ label: 'label', name: 'existing' }, CmdbMode.Edit);

        expect(editComponent.nameControl.disabled).toBeTrue();
    }));

    it('should update initialValue when onRefInputChange is called with the name type', () => {
        component.nameControl.setValue('ref_name', { emitEvent: false });

        component.onRefInputChange('ref_name', 'name');

        expect(component['initialValue']).toBe(component.nameControl.value);
    });

    /* ------------------------------------------- summary rows ------------------------------------------- */

    it('should drop the fields of the previous type when a summary row switches type', () => {
        const previousType = { public_id: 1, label: 'Router', render_meta: { icon: 'fas fa-server' }, fields: [
            { name: 'network_range', label: 'Network Range' }
        ] } as any;
        const nextType = { public_id: 2, label: 'Switch', render_meta: { icon: 'fas fa-plug' }, fields: [
            { name: 'ports', label: 'Ports' }
        ] } as any;
        component.typeList = [previousType, nextType];
        const summary = { type_id: 2, line: null, label: 'Router', fields: ['network_range'], icon: null, prefix: false };
        component.summaries = [summary];

        component.changeSummaryOption(nextType, summary);

        expect(summary.fields).toEqual([]);
        expect(summary.label).toBe('Switch');
        expect(summary.icon).toBe('fas fa-plug');
    });

    it('should keep the fields the newly selected type also holds', () => {
        const nextType = { public_id: 2, label: 'Switch', render_meta: { icon: 'fas fa-plug' }, fields: [
            { name: 'hostname', label: 'Hostname' },
            { name: 'ports', label: 'Ports' }
        ] } as any;
        const summary = { type_id: 2, line: null, label: 'Router', fields: ['hostname', 'network_range'], icon: null, prefix: false };
        component.summaries = [summary];

        component.changeSummaryOption(nextType, summary);

        expect(summary.fields).toEqual(['hostname']);
    });

    it('should only touch the summary row the selection belongs to', () => {
        const nextType = { public_id: 2, label: 'Switch', render_meta: { icon: 'fas fa-plug' }, fields: [] } as any;
        const untouched = { type_id: 2, line: 'keep me', label: 'Switch', fields: ['ports'], icon: null, prefix: false };
        const edited = { type_id: 2, line: null, label: 'Router', fields: ['network_range'], icon: null, prefix: false };
        component.summaries = [untouched, edited];

        component.changeSummaryOption(nextType, edited);

        expect(untouched.fields).toEqual(['ports']);
        expect(untouched.line).toBe('keep me');
        expect(edited.fields).toEqual([]);
    });

    it('should reset the summary row when the type selection is cleared', () => {
        const summary = { type_id: null, line: 'Hostname: {}', label: 'Router', fields: ['network_range'], icon: 'fas fa-server', prefix: false };
        component.summaries = [summary];

        component.changeSummaryOption(undefined as any, summary);

        expect(summary.label).toBe('');
        expect(summary.icon).toBeNull();
        expect(summary.line).toBe('');
        expect(summary.fields).toEqual([]);
    });

    it('should return the same empty field list reference while no type is selected', () => {
        expect(component.summaryFieldFilter(null)).toBe(component.summaryFieldFilter(undefined));
    });

    it('should list the fields of the selected type', () => {
        const fields = [{ name: 'ports', label: 'Ports' }];
        component.typeList = [{ public_id: 7, label: 'Switch', fields } as any];

        expect(component.summaryFieldFilter(7)).toBe(fields);
    });

    it('should write the filtered summaries back to the field so dropped rows stay dropped', () => {
        component.data.ref_types = [1, 2];
        component.data.summaries = [
            { type_id: 1, fields: ['network_range'] },
            { type_id: 2, fields: ['ports'] }
        ];
        component.summaries = component.data.summaries;

        component.data.ref_types = [2];
        component['filterSummaries']();

        expect(component.summaries.map(summary => summary.type_id)).toEqual([2]);
        expect(component.data.summaries).toBe(component.summaries);
    });

    it('should emit a ref field change with the full contract', () => {
        component.nameControl.setValue('ref_name', { emitEvent: false });
        const events: any[] = [];
        const sub = component.fieldChanges$.subscribe(event => events.push(event));

        component.onRefInputChange('some helper', 'helperText');

        sub.unsubscribe();
        expect(events[0]).toEqual(jasmine.objectContaining({
            newValue: 'some helper',
            inputName: 'helperText',
            fieldName: 'ref_name',
            previousName: component['initialValue'],
            elementType: 'ref'
        }));
    });
});
