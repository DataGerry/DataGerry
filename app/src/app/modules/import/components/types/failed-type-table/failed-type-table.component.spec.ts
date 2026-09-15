import { SimpleChange, SimpleChanges } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { FailedTypeTableComponent } from './failed-type-table.component';
import { ImportTypeFailedEntry } from '../../../models/import-type.models';

function failedImportsChange(currentValue: ImportTypeFailedEntry[]): SimpleChanges {
    return { failedImports: new SimpleChange(undefined, currentValue, false) };
}

/**
 * The rejected types section replays the uploaded entry next to the reasons the backend rejected it.
 * The backend joins several reasons into one string, and the entry itself can be anything.
 */
describe('FailedTypeTableComponent (type import - rejected types)', () => {
    let component: FailedTypeTableComponent;
    let fixture: ComponentFixture<FailedTypeTableComponent>;

    /** Applies the report the way the result step binds it. */
    const applyFailedImports = (failedImports: ImportTypeFailedEntry[]) => {
        component.failedImports = failedImports;
        component.ngOnChanges(failedImportsChange(failedImports));
    };

    beforeEach(async () => {
        await TestBed.configureTestingModule({
            declarations: [FailedTypeTableComponent]
        })
            .overrideComponent(FailedTypeTableComponent, { set: { template: '' } })
            .compileComponents();

        fixture = TestBed.createComponent(FailedTypeTableComponent);
        component = fixture.componentInstance;
    });

    describe('rejected type header', () => {
        it('shows label, name and public id of the uploaded entry', () => {
            applyFailedImports([{ failed_type: { public_id: 7, name: 'server', label: 'Server' }, errors: ['nope'] }]);

            expect(component.items[0].label).toBe('Server');
            expect(component.items[0].name).toBe('server');
            expect(component.items[0].publicId).toBe(7);
        });

        it('falls back to the technical name when the entry has no label', () => {
            applyFailedImports([{ failed_type: { name: 'server' }, errors: [] }]);

            expect(component.items[0].label).toBe('server');
        });

        it('falls back to placeholders when the entry has neither label nor name', () => {
            applyFailedImports([{ failed_type: {}, errors: [] }]);

            expect(component.items[0].label).toBe('Unknown type');
            expect(component.items[0].name).toBe('—');
            expect(component.items[0].publicId).toBeNull();
        });

        it('shows no public id when the upload carried a non numeric one', () => {
            applyFailedImports([{ failed_type: { name: 'server', public_id: '7' as any }, errors: [] }]);

            expect(component.items[0].publicId).toBeNull();
        });

        it('survives a report entry that carries no type at all', () => {
            applyFailedImports([{ failed_type: undefined as any, errors: ['nope'] }]);

            expect(component.items[0].label).toBe('Unknown type');
            expect(component.items[0].meta).toEqual([]);
        });

        it('survives a report entry whose type is not an object', () => {
            applyFailedImports([{ failed_type: 'server' as any, errors: ['nope'] }]);

            expect(component.items[0].label).toBe('Unknown type');
        });
    });

    describe('rejection reasons', () => {
        it('shows every reason the backend reported', () => {
            applyFailedImports([{ failed_type: { name: 'server' }, errors: ['Name is taken', 'Fields are missing'] }]);

            expect(component.items[0].errors).toEqual(['Name is taken', 'Fields are missing']);
        });

        it('splits reasons the backend joined into one message', () => {
            applyFailedImports([{ failed_type: { name: 'server' }, errors: ['Name is taken; Fields are missing'] }]);

            expect(component.items[0].errors).toEqual(['Name is taken', 'Fields are missing']);
        });

        it('drops the empty parts of a joined message', () => {
            applyFailedImports([{ failed_type: { name: 'server' }, errors: ['Name is taken;;  ; '] }]);

            expect(component.items[0].errors).toEqual(['Name is taken']);
        });

        it('shows no reason when the backend reported none', () => {
            applyFailedImports([{ failed_type: { name: 'server' }, errors: undefined as any }]);

            expect(component.items[0].errors).toEqual([]);
        });

        it('renders a non string reason instead of dropping it', () => {
            applyFailedImports([{ failed_type: { name: 'server' }, errors: [500 as any] }]);

            expect(component.items[0].errors).toEqual(['500']);
        });
    });

    describe('rejected type meta', () => {
        it('counts fields and sections and shows the version', () => {
            applyFailedImports([{
                failed_type: {
                    name: 'server',
                    version: '1.0.1',
                    fields: [{ name: 'hostname' }, { name: 'serial' }],
                    render_meta: { sections: [{ name: 'general' }] }
                },
                errors: []
            }]);

            expect(component.items[0].meta).toEqual([
                { label: 'Fields', value: '2' },
                { label: 'Sections', value: '1' },
                { label: 'Version', value: '1.0.1' }
            ]);
        });

        it('omits the parts the upload does not carry', () => {
            applyFailedImports([{ failed_type: { name: 'server', fields: [{ name: 'hostname' }] }, errors: [] }]);

            expect(component.items[0].meta).toEqual([{ label: 'Fields', value: '1' }]);
        });

        it('omits empty field and section lists', () => {
            applyFailedImports([{ failed_type: { name: 'server', fields: [], render_meta: { sections: [] } }, errors: [] }]);

            expect(component.items[0].meta).toEqual([]);
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

        it('replaces the list when a second import reports other failures', () => {
            applyFailedImports([{ failed_type: { name: 'server' }, errors: ['nope'] }]);

            applyFailedImports([{ failed_type: { name: 'router' }, errors: ['nope'] }]);

            expect(component.items.length).toBe(1);
            expect(component.items[0].name).toBe('router');
        });
    });
});
