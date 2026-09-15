import { SimpleChange, SimpleChanges } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Router } from '@angular/router';

import { ImportTypeCompleteComponent } from './import-type-complete.component';
import { ImportTypeFailedEntry, ImportTypeResponse } from '../../../models/import-type.models';

function failedEntry(errors: string[] = ['Type already exists']): ImportTypeFailedEntry {
    return { failed_type: { name: 'server' }, errors };
}

function responseChange(currentValue: unknown): SimpleChanges {
    return { importResponse: new SimpleChange(undefined, currentValue, false) };
}

/**
 * The result step of the type import turns the report into one of four outcomes and names the action
 * the user ran. Both drive the banner, so every count combination is covered.
 */
describe('ImportTypeCompleteComponent (type import - result step)', () => {
    let component: ImportTypeCompleteComponent;
    let fixture: ComponentFixture<ImportTypeCompleteComponent>;
    let router: jasmine.SpyObj<Router>;

    /** Applies an import report the way the wizard host binds it. */
    const applyResponse = (response: Partial<ImportTypeResponse> | undefined) => {
        component.importResponse = response as ImportTypeResponse;
        component.ngOnChanges(responseChange(response));
    };

    beforeEach(async () => {
        router = jasmine.createSpyObj<Router>('Router', ['navigate']);

        await TestBed.configureTestingModule({
            declarations: [ImportTypeCompleteComponent],
            providers: [{ provide: Router, useValue: router }]
        })
            .overrideComponent(ImportTypeCompleteComponent, { set: { template: '' } })
            .compileComponents();

        fixture = TestBed.createComponent(ImportTypeCompleteComponent);
        component = fixture.componentInstance;
    });

    describe('before the import was started', () => {
        it('shows no result', () => {
            expect(component.outcome).toBe('empty');
            expect(component.importedCount).toBe(0);
            expect(component.failedCount).toBe(0);
        });
    });

    describe('import outcome', () => {
        it('reports a full success when no type was rejected', () => {
            applyResponse({ success_imports: 2, failed_imports: [] });

            expect(component.outcome).toBe('success');
            expect(component.importedCount).toBe(2);
            expect(component.failedCount).toBe(0);
        });

        it('reports a partial import when some types were rejected', () => {
            applyResponse({ success_imports: 1, failed_imports: [failedEntry()] });

            expect(component.outcome).toBe('partial');
            expect(component.importedCount).toBe(1);
            expect(component.failedCount).toBe(1);
        });

        it('reports a failed import when every type was rejected', () => {
            applyResponse({ success_imports: 0, failed_imports: [failedEntry(), failedEntry()] });

            expect(component.outcome).toBe('failed');
            expect(component.failedCount).toBe(2);
        });

        it('reports an empty import when nothing was imported and nothing failed', () => {
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
        });

        it('re-derives the outcome when the step is used for a second import', () => {
            applyResponse({ success_imports: 2, failed_imports: [] });

            applyResponse({ success_imports: 0, failed_imports: [failedEntry()] });

            expect(component.outcome).toBe('failed');
            expect(component.importedCount).toBe(0);
        });

        it('keeps the previous result when an unrelated input changes', () => {
            applyResponse({ success_imports: 2, failed_imports: [] });

            component.ngOnChanges({ isImporting: new SimpleChange(false, true, false) });

            expect(component.outcome).toBe('success');
            expect(component.importedCount).toBe(2);
        });
    });

    describe('action label', () => {
        it('names the create action', () => {
            component.action = 'create';

            expect(component.actionLabel).toBe('Create new types');
        });

        it('names the update action', () => {
            component.action = 'update';

            expect(component.actionLabel).toBe('Update existing types');
        });
    });

    describe('actions', () => {
        it('asks the wizard host to run the import', () => {
            let emitted = false;
            component.startImportEmitter.subscribe(() => emitted = true);

            component.onStartImport();

            expect(emitted).toBeTrue();
        });

        it('links to the type list', () => {
            component.onTypeListRedirect();

            expect(router.navigate).toHaveBeenCalledWith(['/framework/type/']);
        });
    });
});
