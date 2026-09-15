import { SimpleChange, SimpleChanges } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Router } from '@angular/router';

import { ImportCompleteComponent } from './import-complete.component';
import { ImportFailedEntry, ImportResponse } from '../../../models/import-object.models';

function failedEntry(errors: string[] = ['Field "hostname" is required']): ImportFailedEntry {
    return { failed_object: { public_id: 1, fields: [] }, errors };
}

function responseChange(currentValue: unknown): SimpleChanges {
    return { importResponse: new SimpleChange(undefined, currentValue, false) };
}

/**
 * The completion step turns the import report into one of four outcomes. Everything the banner and the
 * failed-objects section show is derived here, so each combination of counts is covered.
 */
describe('ImportCompleteComponent (object import - result step)', () => {
    let component: ImportCompleteComponent;
    let fixture: ComponentFixture<ImportCompleteComponent>;
    let router: jasmine.SpyObj<Router>;

    /** Applies an import report the way the wizard host binds it. */
    const applyResponse = (response: Partial<ImportResponse> | undefined) => {
        component.importResponse = response as ImportResponse;
        component.ngOnChanges(responseChange(response));
    };

    beforeEach(async () => {
        router = jasmine.createSpyObj<Router>('Router', ['navigate']);

        await TestBed.configureTestingModule({
            declarations: [ImportCompleteComponent],
            providers: [{ provide: Router, useValue: router }]
        })
            .overrideComponent(ImportCompleteComponent, { set: { template: '' } })
            .compileComponents();

        fixture = TestBed.createComponent(ImportCompleteComponent);
        component = fixture.componentInstance;
    });

    describe('before the import was started', () => {
        it('shows no result', () => {
            component.ngOnInit();

            expect(component.outcome).toBe('empty');
            expect(component.importedCount).toBe(0);
            expect(component.failedCount).toBe(0);
        });

        it('discards a report left over from a previous run', () => {
            component.importResponse = { success_imports: 5, failed_imports: [] };

            component.ngOnInit();

            expect(component.importResponse).toBeUndefined();
        });
    });

    describe('import outcome', () => {
        it('reports a full success when nothing failed', () => {
            applyResponse({ success_imports: 3, failed_imports: [] });

            expect(component.outcome).toBe('success');
            expect(component.importedCount).toBe(3);
            expect(component.failedCount).toBe(0);
        });

        it('reports a partial import when some objects failed', () => {
            applyResponse({ success_imports: 2, failed_imports: [failedEntry(), failedEntry()] });

            expect(component.outcome).toBe('partial');
            expect(component.importedCount).toBe(2);
            expect(component.failedCount).toBe(2);
        });

        it('reports a failed import when no object made it through', () => {
            applyResponse({ success_imports: 0, failed_imports: [failedEntry()] });

            expect(component.outcome).toBe('failed');
            expect(component.importedCount).toBe(0);
            expect(component.failedCount).toBe(1);
        });

        it('reports an empty import for a file without any usable row', () => {
            applyResponse({ success_imports: 0, failed_imports: [] });

            expect(component.outcome).toBe('empty');
        });

        it('falls back to zero counts for an incomplete report', () => {
            applyResponse({ message: 'done' });

            expect(component.outcome).toBe('empty');
            expect(component.importedCount).toBe(0);
            expect(component.failedCount).toBe(0);
        });

        it('falls back to zero counts when the report is missing entirely', () => {
            applyResponse(undefined);

            expect(component.outcome).toBe('empty');
            expect(component.importedCount).toBe(0);
        });

        it('re-derives the outcome when the step is used for a second import', () => {
            applyResponse({ success_imports: 3, failed_imports: [] });

            applyResponse({ success_imports: 0, failed_imports: [failedEntry()] });

            expect(component.outcome).toBe('failed');
            expect(component.importedCount).toBe(0);
            expect(component.failedCount).toBe(1);
        });

        it('keeps the previous result when an unrelated input changes', () => {
            applyResponse({ success_imports: 3, failed_imports: [] });

            component.ngOnChanges({ isImporting: new SimpleChange(false, true, false) });

            expect(component.outcome).toBe('success');
            expect(component.importedCount).toBe(3);
        });
    });

    describe('actions', () => {
        it('asks the wizard host to run the import', () => {
            const emitted: unknown[] = [];
            component.startImportEmitter.subscribe((value) => emitted.push(value));

            component.onStartImport();

            expect(emitted).toEqual([null]);
        });

        it('links to the object list of the imported type', () => {
            component.importerConfig = { type_id: 42 } as any;

            component.onListRedirect();

            expect(router.navigate).toHaveBeenCalledWith(['/framework/object/type/', 42]);
        });
    });
});
