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
import { NgbModal, NgbModalRef } from '@ng-bootstrap/ng-bootstrap';
import { Observable, of } from 'rxjs';

import { CmdbMode } from '../../../modes.enum';
import { CmdbMultiDataSection } from '../../../models/cmdb-type';
import { MultiDataSectionEntry, MultiDataSectionSet } from '../../../models/cmdb-object';
import { ObjectService } from '../../../services/object.service';

import {
    MDS_ROW_VALIDATORS,
    MdsCandidateValidationState,
    MdsRowValidator,
    MdsRowValidatorHandle
} from './mds-row-validator';
import { MultiDataSectionComponent } from './multi-data-section.component';
import { getNextMultiDataId } from './mds-id.util';
/* ------------------------------------------------------------------------------------------------------------------ */


interface StubHandle extends MdsRowValidatorHandle {
    validateCandidate: jasmine.Spy;
    destroy: jasmine.Spy;
}


function makeStubHandle(
    state: MdsCandidateValidationState = { valid: true, errors: [] },
    errorAnchorField: string | null = 'dg-interface-ip-address'
): StubHandle {
    return {
        errorAnchorField,
        validateCandidate: jasmine.createSpy('validateCandidate').and.returnValue(of(state)),
        destroy: jasmine.createSpy('destroy')
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


    describe('attachRowValidators()', () => {
        it('does nothing when no validators are registered', () => {
            const { component } = buildComponent();

            (component as any).attachRowValidators();

            expect((component as any).rowValidatorHandles.length).toBe(0);
        });

        it('skips validators that return null (do not apply to this section)', () => {
            const validator = makeStubValidator(null);
            const { component } = buildComponent([validator]);

            (component as any).attachRowValidators();

            expect(validator.attach).toHaveBeenCalledTimes(1);
            expect((component as any).rowValidatorHandles.length).toBe(0);
        });

        it('forwards section and excludeObjectId derived from renderResult', () => {
            const handle = makeStubHandle();
            const validator = makeStubValidator(handle);
            const { component } = buildComponent([validator]);
            (component as any).renderResult = {
                object_information: { object_id: 42 }
            };

            (component as any).attachRowValidators();

            expect(validator.attach).toHaveBeenCalledTimes(1);
            const callArgs = (validator.attach as jasmine.Spy).calls.mostRecent().args;
            expect(callArgs[0]).toBe(component.section);
            expect(callArgs[1]).toEqual({ excludeObjectId: 42 });
        });

        it('passes excludeObjectId:null when there is no renderResult (object create mode)', () => {
            const handle = makeStubHandle();
            const validator = makeStubValidator(handle);
            const { component } = buildComponent([validator]);

            (component as any).attachRowValidators();

            const callArgs = (validator.attach as jasmine.Spy).calls.mostRecent().args;
            expect(callArgs[1]).toEqual({ excludeObjectId: null });
        });

        it('keeps every active handle for later use by the modal', () => {
            const handleA = makeStubHandle();
            const handleB = makeStubHandle();
            const { component } = buildComponent([
                makeStubValidator(handleA),
                makeStubValidator(handleB)
            ]);

            (component as any).attachRowValidators();

            expect((component as any).rowValidatorHandles).toEqual([handleA, handleB]);
        });
    });


    describe('runCandidateValidation()', () => {
        it('returns a permanently-valid result when there are no handles', (done) => {
            const { component } = buildComponent();
            const result$ = (component as any).runCandidateValidation({}, null) as Observable<{
                valid: boolean;
                errors: ReadonlyArray<string>;
            }>;

            result$.subscribe(result => {
                expect(result.valid).toBeTrue();
                expect(result.errors.length).toBe(0);
                done();
            });
        });

        it('forwards the committed rows, form value, and editingRowId to every handle', (done) => {
            const rows: MultiDataSectionSet[] = [{ multi_data_id: 0, data: [] }];
            const handleA = makeStubHandle();
            const handleB = makeStubHandle();
            const { component } = buildComponent();
            (component as any).rowValidatorHandles = [handleA, handleB];
            (component as any).formatedDataSection = buildEntry(rows);

            const candidate = { foo: 'bar' };
            const result$ = (component as any).runCandidateValidation(candidate, 7) as Observable<unknown>;

            result$.subscribe(() => {
                expect(handleA.validateCandidate).toHaveBeenCalledWith(rows, candidate, 7);
                expect(handleB.validateCandidate).toHaveBeenCalledWith(rows, candidate, 7);
                done();
            });
        });

        it('passes an empty object when the form value is null/undefined', (done) => {
            const handle = makeStubHandle();
            const { component } = buildComponent();
            (component as any).rowValidatorHandles = [handle];

            const result$ = (component as any).runCandidateValidation(null, null) as Observable<unknown>;
            result$.subscribe(() => {
                expect(handle.validateCandidate).toHaveBeenCalledWith(jasmine.any(Array), {}, null);
                done();
            });
        });

        it('merges results: any invalid handle makes the overall result invalid', (done) => {
            const handleA = makeStubHandle({ valid: true, errors: [] });
            const handleB = makeStubHandle({ valid: false, errors: ['bad ip'] });
            const { component } = buildComponent();
            (component as any).rowValidatorHandles = [handleA, handleB];

            const result$ = (component as any).runCandidateValidation({}, null) as Observable<{
                valid: boolean;
                errors: ReadonlyArray<string>;
            }>;

            result$.subscribe(result => {
                expect(result.valid).toBeFalse();
                expect(Array.from(result.errors)).toEqual(['bad ip']);
                done();
            });
        });

        it('concatenates error messages across handles', (done) => {
            const handleA = makeStubHandle({ valid: false, errors: ['a', 'b'] });
            const handleB = makeStubHandle({ valid: false, errors: ['c'] });
            const { component } = buildComponent();
            (component as any).rowValidatorHandles = [handleA, handleB];

            const result$ = (component as any).runCandidateValidation({}, null) as Observable<{
                valid: boolean;
                errors: ReadonlyArray<string>;
            }>;

            result$.subscribe(result => {
                expect(Array.from(result.errors)).toEqual(['a', 'b', 'c']);
                done();
            });
        });
    });


    describe('applyCandidateValidatorToModal()', () => {
        it('is a no-op when no validators have attached', () => {
            const { component } = buildComponent();
            const componentInstance: any = {};
            const modalRef = { componentInstance } as unknown as NgbModalRef;

            (component as any).applyCandidateValidatorToModal(modalRef, null);

            expect(componentInstance.externalValidator).toBeUndefined();
            expect(componentInstance.errorAnchorField).toBeUndefined();
        });

        it('wires a validator function and the error anchor field onto the modal instance', () => {
            const handle = makeStubHandle({ valid: false, errors: ['bad'] }, 'dg-interface-ip-address');
            const { component } = buildComponent();
            (component as any).rowValidatorHandles = [handle];
            (component as any).formatedDataSection = buildEntry();

            const componentInstance: any = {};
            const modalRef = { componentInstance } as unknown as NgbModalRef;

            (component as any).applyCandidateValidatorToModal(modalRef, 3);

            expect(typeof componentInstance.externalValidator).toBe('function');
            expect(componentInstance.errorAnchorField).toBe('dg-interface-ip-address');

            // Invoke the wired validator and verify it threads editingRowId through to the handle.
            componentInstance.externalValidator({ foo: 'bar' }).subscribe(() => {});
            expect(handle.validateCandidate).toHaveBeenCalledWith(jasmine.any(Array), { foo: 'bar' }, 3);
        });

        it('picks the first non-null errorAnchorField across multiple handles', () => {
            const handleA = makeStubHandle({ valid: true, errors: [] }, null);
            const handleB = makeStubHandle({ valid: true, errors: [] }, 'dg-interface-ip-address');
            const { component } = buildComponent();
            (component as any).rowValidatorHandles = [handleA, handleB];

            const componentInstance: any = {};
            (component as any).applyCandidateValidatorToModal({ componentInstance } as any, null);

            expect(componentInstance.errorAnchorField).toBe('dg-interface-ip-address');
        });
    });


    describe('ngOnDestroy()', () => {
        it('destroys every attached handle', () => {
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
        });

        it('does not throw when ngOnDestroy is called without any attached handles', () => {
            const { component } = buildComponent();

            expect(() => component.ngOnDestroy()).not.toThrow();
        });
    });
});


/* ------------------------------------------------------------------------------------------------------------------ */

describe('MultiDataSectionComponent (row id lifecycle)', () => {
    let modalService: jasmine.SpyObj<NgbModal>;
    let objectService: jasmine.SpyObj<ObjectService>;
    let component: MultiDataSectionComponent;

    const ipValue = (id: number): any =>
        component.formatedDataSection.values
            .find((r) => r.multi_data_id === id)?.data.find((d) => d.name === 'ip')?.value;

    // Mirrors what onAddRowClicked does after the modal resolves, without opening the modal.
    const addRow = (values: Record<string, any>): number => {
        const id = getNextMultiDataId(component.formatedDataSection);
        (component as any).addNewValuesToControl(values, id);
        component.tableMultiDataValues.push({ 'dg-multiDataRowIndex': id, ...values });
        component.formatedDataSection.highest_id = id;
        return id;
    };

    beforeEach(() => {
        modalService = jasmine.createSpyObj<NgbModal>('NgbModal', ['open']);
        objectService = jasmine.createSpyObj<ObjectService>('ObjectService', ['getObjects']);
        objectService.getObjects.and.returnValue(of({ results: [], total: 0, count: 0 }) as any);

        TestBed.resetTestingModule();
        TestBed.configureTestingModule({
            declarations: [MultiDataSectionComponent],
            providers: [
                { provide: NgbModal, useValue: modalService },
                { provide: ObjectService, useValue: objectService }
            ],
            schemas: [NO_ERRORS_SCHEMA]
        });

        // No detectChanges(): ngOnInit is skipped so we drive the row methods on a clean state.
        component = TestBed.createComponent(MultiDataSectionComponent).componentInstance;
        component.typeInstance = { fields: [{ name: 'ip', type: 'text' }] } as any;
        component.form = new UntypedFormGroup({});
        // A backend-created object: one row with multi_data_id 1 and highest_id 1 (the case that
        // used to make a newly added row reuse id 1).
        (component as any).formatedDataSection = {
            section_id: 'net',
            highest_id: 1,
            values: [{ multi_data_id: 1, data: [{ name: 'ip', value: 'existing' }] }]
        };
        component.tableMultiDataValues = [{ 'dg-multiDataRowIndex': 1, ip: 'existing' }];
    });

    it('gives an added row an id distinct from the existing row', () => {
        const id = addRow({ ip: 'added' });

        const ids = component.formatedDataSection.values.map((r) => r.multi_data_id);
        expect(id).toBe(2);
        expect(ids).toEqual([1, 2]);
        expect(new Set(ids).size).toBe(2);
        expect(component.formatedDataSection.highest_id).toBe(2);
    });

    it('editing the added row leaves the existing row untouched', () => {
        const id = addRow({ ip: 'added' });

        (component as any).updateNewValues({ ip: 'added-edited' }, id);

        expect(ipValue(1)).toBe('existing');
        expect(ipValue(id)).toBe('added-edited');
    });

    it('deleting the added row keeps the existing row', () => {
        const id = addRow({ ip: 'added' });

        component.removeDataSet(id);

        expect(component.formatedDataSection.values.map((r) => r.multi_data_id)).toEqual([1]);
        expect(component.tableMultiDataValues.map((r) => r['dg-multiDataRowIndex'])).toEqual([1]);
        expect(ipValue(1)).toBe('existing');
    });

    it('deleting the existing row keeps the added row (inverse)', () => {
        const id = addRow({ ip: 'added' });

        component.removeDataSet(1);

        expect(component.formatedDataSection.values.map((r) => r.multi_data_id)).toEqual([id]);
        expect(ipValue(id)).toBe('added');
    });

    it('supports several adds/edits/deletes without any id collision', () => {
        const a = addRow({ ip: 'a' }); // 2
        const b = addRow({ ip: 'b' }); // 3

        (component as any).updateNewValues({ ip: 'b-edited' }, b);
        component.removeDataSet(a);

        const c = addRow({ ip: 'c' }); // 4 — must not reuse 2

        const ids = component.formatedDataSection.values.map((r) => r.multi_data_id);
        expect([a, b, c]).toEqual([2, 3, 4]);
        expect(new Set(ids).size).toBe(ids.length);
        expect(ipValue(1)).toBe('existing');
        expect(ipValue(b)).toBe('b-edited');
        expect(ipValue(c)).toBe('c');
    });
});
