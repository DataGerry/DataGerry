import { SimpleChange, SimpleChanges } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { FailedImportTableComponent } from './failed-import-table.component';
import { ImportFailedEntry } from '../../../models/import-object.models';
import { CmdbType } from 'src/app/framework/models/cmdb-type';

function buildType(overrides: Partial<CmdbType> = {}): CmdbType {
    return { public_id: 42, name: 'server', label: 'Server', fields: [], ...overrides } as CmdbType;
}

function failedImportsChange(): SimpleChanges {
    return { failedImports: new SimpleChange(undefined, [], false) };
}

/**
 * The failed objects section replays what the user uploaded next to the reasons it was rejected.
 * The payload comes straight from the backend, so every part of it can be missing or of any shape.
 */
describe('FailedImportTableComponent (object import - rejected objects)', () => {
    let component: FailedImportTableComponent;
    let fixture: ComponentFixture<FailedImportTableComponent>;

    /** Applies the report the way the completion step binds it. */
    const applyFailedImports = (failedImports: ImportFailedEntry[], typeInstance?: CmdbType) => {
        component.failedImports = failedImports;
        component.typeInstance = typeInstance;
        component.ngOnChanges(failedImportsChange());
    };

    beforeEach(async () => {
        await TestBed.configureTestingModule({
            declarations: [FailedImportTableComponent]
        })
            .overrideComponent(FailedImportTableComponent, { set: { template: '' } })
            .compileComponents();

        fixture = TestBed.createComponent(FailedImportTableComponent);
        component = fixture.componentInstance;
    });

    describe('rejected object header', () => {
        it('shows the type label the backend reported', () => {
            applyFailedImports([{ failed_object: { type_label: 'Router', public_id: 7 }, errors: ['broken'] }]);

            expect(component.items[0].typeLabel).toBe('Router');
            expect(component.items[0].publicId).toBe(7);
            expect(component.items[0].errors).toEqual(['broken']);
        });

        it('falls back to the label of the selected type', () => {
            applyFailedImports([{ failed_object: {}, errors: [] }], buildType({ label: 'Server' }));

            expect(component.items[0].typeLabel).toBe('Server');
        });

        it('falls back to a generic label when neither is known', () => {
            applyFailedImports([{ failed_object: {}, errors: [] }]);

            expect(component.items[0].typeLabel).toBe('Object');
        });

        it('shows no public id when the upload did not carry a numeric one', () => {
            applyFailedImports([{ failed_object: { public_id: 'abc' as any }, errors: [] }]);

            expect(component.items[0].publicId).toBeNull();
        });

        it('reports no errors instead of failing when the backend sent none', () => {
            applyFailedImports([{ failed_object: {}, errors: undefined as any }]);

            expect(component.items[0].errors).toEqual([]);
        });

        it('survives a report entry without any object', () => {
            applyFailedImports([{ failed_object: undefined as any, errors: ['broken'] }]);

            expect(component.items[0].typeLabel).toBe('Object');
            expect(component.items[0].values).toEqual([]);
        });
    });

    describe('rejected object values', () => {
        it('labels every value with the field label of the selected type', () => {
            applyFailedImports(
                [{ failed_object: { fields: [{ name: 'hostname', value: 'srv-01' }] }, errors: [] }],
                buildType({ fields: [{ name: 'hostname', label: 'Host name', type: 'text' }] })
            );

            expect(component.items[0].values).toEqual([{ label: 'Host name', value: 'srv-01' }]);
        });

        it('falls back to the technical field name for fields the type does not know', () => {
            applyFailedImports([{ failed_object: { fields: [{ name: 'unknown_field', value: 'x' }] }, errors: [] }], buildType());

            expect(component.items[0].values).toEqual([{ label: 'unknown_field', value: 'x' }]);
        });

        it('hides fields the user left empty', () => {
            applyFailedImports([{
                failed_object: {
                    fields: [
                        { name: 'a', value: '' },
                        { name: 'b', value: null },
                        { name: 'c', value: undefined },
                        { name: 'd', value: 'kept' }
                    ]
                },
                errors: []
            }]);

            expect(component.items[0].values).toEqual([{ label: 'd', value: 'kept' }]);
        });

        it('keeps values that are falsy but meaningful', () => {
            applyFailedImports([{
                failed_object: { fields: [{ name: 'count', value: 0 }, { name: 'active', value: false }] },
                errors: []
            }]);

            expect(component.items[0].values).toEqual([
                { label: 'count', value: '0' },
                { label: 'active', value: 'false' }
            ]);
        });

        it('serialises structured values so they stay readable', () => {
            applyFailedImports([{
                failed_object: { fields: [{ name: 'meta', value: { a: 1 } }, { name: 'tags', value: ['x', 'y'] }] },
                errors: []
            }]);

            expect(component.items[0].values).toEqual([
                { label: 'meta', value: '{"a":1}' },
                { label: 'tags', value: '["x","y"]' }
            ]);
        });

        it('shows nothing for an object without fields', () => {
            applyFailedImports([{ failed_object: { public_id: 1 }, errors: ['broken'] }]);

            expect(component.items[0].values).toEqual([]);
        });
    });

    describe('empty and changing reports', () => {
        it('shows nothing for an import without failures', () => {
            applyFailedImports([]);

            expect(component.items).toEqual([]);
        });

        it('shows nothing when no report was bound at all', () => {
            applyFailedImports(undefined as any);

            expect(component.items).toEqual([]);
        });

        it('relabels the values when another type is bound', () => {
            applyFailedImports([{ failed_object: { fields: [{ name: 'hostname', value: 'srv-01' }] }, errors: [] }]);
            expect(component.items[0].values[0].label).toBe('hostname');

            component.typeInstance = buildType({ fields: [{ name: 'hostname', label: 'Host name', type: 'text' }] });
            component.ngOnChanges({ typeInstance: new SimpleChange(undefined, component.typeInstance, false) });

            expect(component.items[0].values[0].label).toBe('Host name');
        });
    });
});
