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
