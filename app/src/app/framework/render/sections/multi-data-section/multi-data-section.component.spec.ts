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
import { UntypedFormGroup } from '@angular/forms';
import { NgbModal } from '@ng-bootstrap/ng-bootstrap';
import { BehaviorSubject, of } from 'rxjs';

import { CmdbMode } from '../../../modes.enum';
import { CmdbMultiDataSection } from '../../../models/cmdb-type';
import { MultiDataSectionEntry, MultiDataSectionSet } from '../../../models/cmdb-object';
import { ObjectService } from '../../../services/object.service';

import {
    MDS_ROW_VALIDATORS,
    MdsRowValidator,
    MdsRowValidatorHandle,
    MdsValidationState,
    VALID_MDS_STATE
} from './mds-row-validator';
import { MultiDataSectionComponent } from './multi-data-section.component';
/* ------------------------------------------------------------------------------------------------------------------ */


/**
 * Stub handle that lets a test push state changes through a backing BehaviorSubject and
 * spies on validate / destroy so the MDS lifecycle can be asserted in isolation.
 */
interface StubHandle extends MdsRowValidatorHandle {
    pushState(state: MdsValidationState): void;
    validate: jasmine.Spy;
    destroy: jasmine.Spy;
}


function makeStubHandle(initialState: MdsValidationState = VALID_MDS_STATE): StubHandle {
    const subject = new BehaviorSubject<MdsValidationState>(initialState);
    return {
        state$: subject.asObservable(),
        validate: jasmine.createSpy('validate'),
        destroy: jasmine.createSpy('destroy'),
        pushState: (state: MdsValidationState) => subject.next(state)
    };
}


function makeStubValidator(handle: MdsRowValidatorHandle | null): MdsRowValidator {
    return { attach: jasmine.createSpy('attach').and.returnValue(handle) };
}


function buildSection(name = 'multi-data-section-x'): CmdbMultiDataSection {
    return {
        type: 'multi-data-section',
        name,
        label: 'Test',
        fields: [],
        hidden_fields: []
    } as CmdbMultiDataSection;
}


function buildEntry(values: MultiDataSectionSet[] = []): MultiDataSectionEntry {
    return {
        section_id: 'mds-section',
        highest_id: values.length,
        values
    };
}


describe('MultiDataSectionComponent (validator integration)', () => {
    let modalService: jasmine.SpyObj<NgbModal>;
    let objectService: jasmine.SpyObj<ObjectService>;

    function buildComponent(validators: MdsRowValidator[] = []): {
        fixture: ComponentFixture<MultiDataSectionComponent>;
        component: MultiDataSectionComponent;
    } {
        TestBed.resetTestingModule();
        TestBed.configureTestingModule({
            declarations: [MultiDataSectionComponent],
            providers: [
                { provide: NgbModal, useValue: modalService },
                { provide: ObjectService, useValue: objectService },
                ...validators.map(useValue => ({
                    provide: MDS_ROW_VALIDATORS,
                    useValue,
                    multi: true
                }))
            ],
            schemas: [NO_ERRORS_SCHEMA]
        });

        const fixture = TestBed.createComponent(MultiDataSectionComponent);
        const component = fixture.componentInstance;

        // Sensible defaults so private helpers don't blow up when accessed directly.
        component.section = buildSection();
        component.fields = [];
        component.form = new UntypedFormGroup({});
        component.mode = CmdbMode.Create;
        (component as any).formatedDataSection = buildEntry();

        return { fixture, component };
    }

    beforeEach(() => {
        modalService = jasmine.createSpyObj<NgbModal>('NgbModal', ['open']);
        objectService = jasmine.createSpyObj<ObjectService>('ObjectService', ['getObjects']);
        objectService.getObjects.and.returnValue(of({
            results: [],
            total: 0,
            count: 0,
            parameters: { limit: 0, sort: 'public_id', order: 1, page: 1 }
        }) as any);
    });


    describe('mergeValidationStates()', () => {
        it('returns a permanently-valid state when no states are provided', () => {
            const { component } = buildComponent();
            const merged = (component as any).mergeValidationStates([]);

            expect(merged.valid).toBeTrue();
            expect(merged.invalidRowIndices).toEqual([]);
        });

        it('returns valid:true when every state is valid', () => {
            const { component } = buildComponent();
            const merged = (component as any).mergeValidationStates([
                { valid: true, invalidRowIndices: [] },
                { valid: true, invalidRowIndices: [] }
            ]);

            expect(merged.valid).toBeTrue();
            expect(merged.invalidRowIndices).toEqual([]);
        });

        it('returns valid:false the moment any state is invalid', () => {
            const { component } = buildComponent();
            const merged = (component as any).mergeValidationStates([
                { valid: true, invalidRowIndices: [] },
                { valid: false, invalidRowIndices: [3] }
            ]);

            expect(merged.valid).toBeFalse();
            expect(merged.invalidRowIndices).toEqual([3]);
        });

        it('unions invalid row indices across states without duplicates', () => {
            const { component } = buildComponent();
            const merged = (component as any).mergeValidationStates([
                { valid: false, invalidRowIndices: [1, 2] },
                { valid: false, invalidRowIndices: [2, 3] },
                { valid: false, invalidRowIndices: [3, 4] }
            ]);

            expect(merged.valid).toBeFalse();
            expect((merged.invalidRowIndices as number[]).sort()).toEqual([1, 2, 3, 4]);
        });
    });


    describe('rowValidationClass()', () => {
        it('returns mds-row-invalid for rows whose multi_data_id is flagged', () => {
            const { component } = buildComponent();
            component.validationState = { valid: false, invalidRowIndices: [2, 5] };

            expect(component.rowValidationClass({ 'dg-multiDataRowIndex': 2 })).toBe('mds-row-invalid');
            expect(component.rowValidationClass({ 'dg-multiDataRowIndex': 5 })).toBe('mds-row-invalid');
        });

        it('returns an empty string for rows that are not flagged', () => {
            const { component } = buildComponent();
            component.validationState = { valid: false, invalidRowIndices: [2] };

            expect(component.rowValidationClass({ 'dg-multiDataRowIndex': 1 })).toBe('');
            expect(component.rowValidationClass({ 'dg-multiDataRowIndex': 99 })).toBe('');
        });

        it('returns an empty string when the row index is missing or non-numeric', () => {
            const { component } = buildComponent();
            component.validationState = { valid: false, invalidRowIndices: [2] };

            expect(component.rowValidationClass({})).toBe('');
            expect(component.rowValidationClass({ 'dg-multiDataRowIndex': '2' })).toBe('');
            expect(component.rowValidationClass(undefined)).toBe('');
            expect(component.rowValidationClass(null)).toBe('');
        });
    });


    describe('shouldRunInitialValidation()', () => {
        it('returns false in View mode regardless of row count', () => {
            const { component } = buildComponent();
            component.mode = CmdbMode.View;
            (component as any).formatedDataSection = buildEntry([{ multi_data_id: 0, data: [] }]);

            expect((component as any).shouldRunInitialValidation()).toBeFalse();
        });

        it('returns false in editable modes when there are no existing rows', () => {
            const { component } = buildComponent();
            component.mode = CmdbMode.Edit;
            (component as any).formatedDataSection = buildEntry([]);

            expect((component as any).shouldRunInitialValidation()).toBeFalse();
        });

        it('returns true in Edit mode when rows already exist', () => {
            const { component } = buildComponent();
            component.mode = CmdbMode.Edit;
            (component as any).formatedDataSection = buildEntry([{ multi_data_id: 0, data: [] }]);

            expect((component as any).shouldRunInitialValidation()).toBeTrue();
        });

        it('returns true in Create mode when rows already exist', () => {
            const { component } = buildComponent();
            component.mode = CmdbMode.Create;
            (component as any).formatedDataSection = buildEntry([{ multi_data_id: 0, data: [] }]);

            expect((component as any).shouldRunInitialValidation()).toBeTrue();
        });
    });


    describe('attachRowValidators()', () => {
        it('does nothing when no validators are registered', () => {
            const { component } = buildComponent();

            (component as any).attachRowValidators();

            expect((component as any).rowValidatorHandles.length).toBe(0);
            expect(component.validationState).toEqual(VALID_MDS_STATE);
        });

        it('skips validators that return null (do not apply to this section)', () => {
            const validator = makeStubValidator(null);
            const { component } = buildComponent([validator]);

            (component as any).attachRowValidators();

            expect(validator.attach).toHaveBeenCalledTimes(1);
            expect((component as any).rowValidatorHandles.length).toBe(0);
            expect(component.validationState).toEqual(VALID_MDS_STATE);
        });

        it('forwards form, section, and excludeObjectId derived from renderResult', () => {
            const handle = makeStubHandle();
            const validator = makeStubValidator(handle);
            const { component } = buildComponent([validator]);
            (component as any).renderResult = {
                object_information: { object_id: 42 }
            };

            (component as any).attachRowValidators();

            expect(validator.attach).toHaveBeenCalledTimes(1);
            const callArgs = (validator.attach as jasmine.Spy).calls.mostRecent().args;
            expect(callArgs[0]).toBe(component.form);
            expect(callArgs[1]).toBe(component.section);
            expect(callArgs[2]).toEqual({ excludeObjectId: 42 });
        });

        it('passes excludeObjectId:null when there is no renderResult (object create mode)', () => {
            const handle = makeStubHandle();
            const validator = makeStubValidator(handle);
            const { component } = buildComponent([validator]);

            (component as any).attachRowValidators();

            const callArgs = (validator.attach as jasmine.Spy).calls.mostRecent().args;
            expect(callArgs[2]).toEqual({ excludeObjectId: null });
        });

        it('subscribes to the active handle and reflects its emissions in validationState', () => {
            const handle = makeStubHandle({ valid: false, invalidRowIndices: [3] });
            const validator = makeStubValidator(handle);
            const { component } = buildComponent([validator]);

            (component as any).attachRowValidators();

            expect((component as any).rowValidatorHandles.length).toBe(1);
            expect(component.validationState.valid).toBeFalse();
            expect(component.validationState.invalidRowIndices).toEqual([3]);

            // Push a fresh state through and verify the component picks it up live.
            handle.pushState({ valid: true, invalidRowIndices: [] });
            expect(component.validationState.valid).toBeTrue();
            expect(component.validationState.invalidRowIndices).toEqual([]);
        });

        it('merges state from multiple validators into a single validationState', () => {
            const handleA = makeStubHandle({ valid: true, invalidRowIndices: [] });
            const handleB = makeStubHandle({ valid: false, invalidRowIndices: [7] });
            const { component } = buildComponent([
                makeStubValidator(handleA),
                makeStubValidator(handleB)
            ]);

            (component as any).attachRowValidators();

            expect(component.validationState.valid).toBeFalse();
            expect(component.validationState.invalidRowIndices).toEqual([7]);

            handleA.pushState({ valid: false, invalidRowIndices: [1] });
            expect(component.validationState.valid).toBeFalse();
            expect((component.validationState.invalidRowIndices as number[]).sort()).toEqual([1, 7]);
        });

        it('runs initial validation when there are existing rows in editable modes', () => {
            const handle = makeStubHandle();
            const { component } = buildComponent([makeStubValidator(handle)]);
            component.mode = CmdbMode.Edit;
            (component as any).formatedDataSection = buildEntry([{ multi_data_id: 0, data: [] }]);

            (component as any).attachRowValidators();

            expect(handle.validate).toHaveBeenCalledTimes(1);
            expect(handle.validate).toHaveBeenCalledWith((component as any).formatedDataSection.values);
        });

        it('does NOT run initial validation when no rows exist', () => {
            const handle = makeStubHandle();
            const { component } = buildComponent([makeStubValidator(handle)]);
            component.mode = CmdbMode.Edit;
            (component as any).formatedDataSection = buildEntry([]);

            (component as any).attachRowValidators();

            expect(handle.validate).not.toHaveBeenCalled();
        });

        it('does NOT run initial validation in View mode', () => {
            const handle = makeStubHandle();
            const { component } = buildComponent([makeStubValidator(handle)]);
            component.mode = CmdbMode.View;
            (component as any).formatedDataSection = buildEntry([{ multi_data_id: 0, data: [] }]);

            (component as any).attachRowValidators();

            expect(handle.validate).not.toHaveBeenCalled();
        });
    });


    describe('runMdsValidation()', () => {
        it('calls validate on every attached handle with the current rows', () => {
            const handleA = makeStubHandle();
            const handleB = makeStubHandle();
            const { component } = buildComponent();
            (component as any).rowValidatorHandles = [handleA, handleB];
            const rows: MultiDataSectionSet[] = [{ multi_data_id: 0, data: [] }];
            (component as any).formatedDataSection = buildEntry(rows);

            (component as any).runMdsValidation();

            expect(handleA.validate).toHaveBeenCalledWith(rows);
            expect(handleB.validate).toHaveBeenCalledWith(rows);
        });

        it('is a safe no-op when no handles have been attached', () => {
            const { component } = buildComponent();

            expect(() => (component as any).runMdsValidation()).not.toThrow();
        });
    });


    describe('ngOnDestroy()', () => {
        it('destroys every attached handle and stops listening to state emissions', () => {
            const handleA = makeStubHandle();
            const handleB = makeStubHandle();
            const { component } = buildComponent([
                makeStubValidator(handleA),
                makeStubValidator(handleB)
            ]);
            (component as any).attachRowValidators();

            component.ngOnDestroy();

            expect(handleA.destroy).toHaveBeenCalled();
            expect(handleB.destroy).toHaveBeenCalled();

            // After destroy, late state pushes must not leak into the component.
            const before = component.validationState;
            handleA.pushState({ valid: false, invalidRowIndices: [99] });
            expect(component.validationState).toBe(before);
        });

        it('does not throw when ngOnDestroy is called without any attached handles', () => {
            const { component } = buildComponent();

            expect(() => component.ngOnDestroy()).not.toThrow();
        });
    });
});
