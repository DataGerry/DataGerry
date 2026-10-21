import { ComponentFixture, TestBed } from '@angular/core/testing';
import { MovingDirection } from '@rg-software/angular-archwizard';
import { of, throwError } from 'rxjs';

import { ImportTypesComponent } from './import-types.component';
import { ImportService } from 'src/app/modules/import/services/import.service';
import { LoaderService } from 'src/app/core/services/loader.service';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { ImportTypeEntry } from '../../../models/import-type.models';
import { ParsedTypeFile } from '../select-file-drag-drop/select-file-drag-drop.component';

function buildEntry(name: string, overrides: Partial<ImportTypeEntry> = {}): ImportTypeEntry {
    return { name, label: name.toUpperCase(), fields: [], ...overrides };
}

function buildUpload(types: ImportTypeEntry[], fileName = 'types.json'): ParsedTypeFile {
    return { file: new File([JSON.stringify(types)], fileName, { type: 'application/json' }), types };
}

/**
 * The type import wizard keeps the uploaded file, the prunable working copy of it and the chosen
 * action. These tests walk the whole flow including going back and forth between the steps.
 */
describe('ImportTypesComponent (type import wizard host)', () => {
    let component: ImportTypesComponent;
    let fixture: ComponentFixture<ImportTypesComponent>;

    let importService: jasmine.SpyObj<ImportService>;
    let loaderService: jasmine.SpyObj<LoaderService>;
    let toastService: jasmine.SpyObj<ToastService>;

    /** Reads back the multipart body the wizard handed to the service. */
    const uploadedTypes = (spy: jasmine.Spy): ImportTypeEntry[] => {
        return JSON.parse((spy.calls.mostRecent().args[0] as FormData).get('uploadFile') as string);
    };

    beforeEach(async () => {
        importService = jasmine.createSpyObj<ImportService>('ImportService', ['postCreateTypeParser', 'postUpdateTypeParser']);
        importService.postCreateTypeParser.and.returnValue(of({ message: 'ok', success_imports: 1, failed_imports: [] }));
        importService.postUpdateTypeParser.and.returnValue(of({ message: 'ok', success_imports: 1, failed_imports: [] }));

        loaderService = jasmine.createSpyObj<LoaderService>('LoaderService', ['show', 'hide'], { isLoading$: of(false) });
        toastService = jasmine.createSpyObj<ToastService>('ToastService', ['error']);

        await TestBed.configureTestingModule({
            declarations: [ImportTypesComponent],
            providers: [
                { provide: ImportService, useValue: importService },
                { provide: LoaderService, useValue: loaderService },
                { provide: ToastService, useValue: toastService }
            ]
        })
            .overrideComponent(ImportTypesComponent, { set: { template: '' } })
            .compileComponents();

        fixture = TestBed.createComponent(ImportTypesComponent);
        component = fixture.componentInstance;
    });

    describe('uploading a file', () => {
        it('keeps the file meta and the parsed types', () => {
            const upload = buildUpload([buildEntry('server'), buildEntry('router')], 'export.json');

            component.onFileParsed(upload);

            expect(component.fileName).toBe('export.json');
            expect(component.fileSize).toBe(upload.file.size);
            expect(component.parsedTypes.length).toBe(2);
        });

        it('works on a copy of the upload, so pruning cannot destroy the original', () => {
            const upload = buildUpload([buildEntry('server')]);

            component.onFileParsed(upload);

            expect(component.parsedTypes).not.toBe(upload.types);
            expect(component.parsedTypes).toEqual(upload.types);
        });

        it('survives an upload without a file handle', () => {
            component.onFileParsed({ file: undefined, types: [buildEntry('server')] });

            expect(component.fileName).toBe('');
            expect(component.fileSize).toBeUndefined();
            expect(component.parsedTypes.length).toBe(1);
        });

        it('invalidates a report the user may already have seen', () => {
            component.importResponse = { message: 'old', success_imports: 4, failed_imports: [] };

            component.onFileParsed(buildUpload([buildEntry('server')]));

            expect(component.importResponse).toBeUndefined();
        });

        it('replaces the previous upload when another file is chosen', () => {
            component.onFileParsed(buildUpload([buildEntry('server')], 'first.json'));

            component.onFileParsed(buildUpload([buildEntry('router'), buildEntry('switch')], 'second.json'));

            expect(component.fileName).toBe('second.json');
            expect(component.parsedTypes.map((type) => type.name)).toEqual(['router', 'switch']);
        });
    });

    describe('clearing the file', () => {
        it('resets the whole wizard state', () => {
            component.onFileParsed(buildUpload([buildEntry('server')]));
            component.importResponse = { message: 'ok', success_imports: 1, failed_imports: [] };

            component.onFileCleared();

            expect(component.fileName).toBe('');
            expect(component.fileSize).toBeUndefined();
            expect(component.parsedTypes).toEqual([]);
            expect(component.importResponse).toBeUndefined();
        });
    });

    describe('going back to the file step', () => {
        it('restores the types a pruned review removed', () => {
            component.onFileParsed(buildUpload([buildEntry('server'), buildEntry('router')]));
            component.onTypeRemoved(0);

            component.onFileStepEnter();

            expect(component.parsedTypes.map((type) => type.name)).toEqual(['server', 'router']);
            expect(component.importResponse).toBeUndefined();
        });

        it('restores the list even when every type was removed', () => {
            component.onFileParsed(buildUpload([buildEntry('server')]));
            component.onTypeRemoved(0);
            expect(component.parsedTypes).toEqual([]);

            component.onFileStepEnter();

            expect(component.parsedTypes.length).toBe(1);
        });

        it('leaves an untouched list alone', () => {
            component.onFileParsed(buildUpload([buildEntry('server')]));
            const current = component.parsedTypes;

            component.onFileStepEnter();

            expect(component.parsedTypes).toBe(current);
        });

        it('does nothing when no file was uploaded yet', () => {
            component.onFileStepEnter();

            expect(component.parsedTypes).toEqual([]);
        });
    });

    describe('reviewing the upload', () => {
        it('removes the entry at the given position', () => {
            component.onFileParsed(buildUpload([buildEntry('server'), buildEntry('router'), buildEntry('switch')]));

            component.onTypeRemoved(1);

            expect(component.parsedTypes.map((type) => type.name)).toEqual(['server', 'switch']);
        });

        it('hands a new array down, so the preview list picks the removal up', () => {
            component.onFileParsed(buildUpload([buildEntry('server'), buildEntry('router')]));
            const before = component.parsedTypes;

            component.onTypeRemoved(0);

            expect(component.parsedTypes).not.toBe(before);
        });

        it('invalidates a report that belongs to the unpruned upload', () => {
            component.onFileParsed(buildUpload([buildEntry('server'), buildEntry('router')]));
            component.importResponse = { message: 'ok', success_imports: 2, failed_imports: [] };

            component.onTypeRemoved(0);

            expect(component.importResponse).toBeUndefined();
        });

        it('keeps the chosen action', () => {
            component.onActionChange('update');

            expect(component.action).toBe('update');
        });
    });

    describe('step navigation guard', () => {
        it('blocks moving forward while no type is left', () => {
            expect(component.canLeaveWithTypes(MovingDirection.Forwards)).toBeFalse();
        });

        it('allows moving forward once the upload carries a type', () => {
            component.onFileParsed(buildUpload([buildEntry('server')]));

            expect(component.canLeaveWithTypes(MovingDirection.Forwards)).toBeTrue();
        });

        it('always allows going back or staying', () => {
            expect(component.canLeaveWithTypes(MovingDirection.Backwards)).toBeTrue();
            expect(component.canLeaveWithTypes(MovingDirection.Stay)).toBeTrue();
        });
    });

    describe('starting the import', () => {
        beforeEach(() => component.onFileParsed(buildUpload([buildEntry('server'), buildEntry('router')])));

        it('creates new types by default', () => {
            component.startImport();

            expect(importService.postCreateTypeParser).toHaveBeenCalled();
            expect(importService.postUpdateTypeParser).not.toHaveBeenCalled();
        });

        it('updates existing types when the user picked that action', () => {
            component.onActionChange('update');

            component.startImport();

            expect(importService.postUpdateTypeParser).toHaveBeenCalled();
            expect(importService.postCreateTypeParser).not.toHaveBeenCalled();
        });

        it('sends exactly the types that survived the review', () => {
            component.onTypeRemoved(0);

            component.startImport();

            expect(uploadedTypes(importService.postCreateTypeParser).map((type) => type.name)).toEqual(['router']);
        });

        it('keeps the report for the result step', () => {
            importService.postCreateTypeParser.and.returnValue(of({ message: 'done', success_imports: 2, failed_imports: [] }));

            component.startImport();

            expect(component.importResponse).toEqual({ message: 'done', success_imports: 2, failed_imports: [] });
        });

        it('fills in the parts an incomplete report leaves out', () => {
            importService.postCreateTypeParser.and.returnValue(of({ message: 'done' }));

            component.startImport();

            expect(component.importResponse).toEqual({ message: 'done', success_imports: 0, failed_imports: [] });
        });

        it('survives an empty answer from the backend', () => {
            importService.postCreateTypeParser.and.returnValue(of(null));

            component.startImport();

            expect(component.importResponse).toEqual({ message: undefined, success_imports: 0, failed_imports: [] });
        });

        it('shows the loader while importing and hides it afterwards', () => {
            component.startImport();

            expect(loaderService.show).toHaveBeenCalled();
            expect(loaderService.hide).toHaveBeenCalled();
            expect(component.isImporting).toBeFalse();
        });

        it('does nothing when the review left no type to import', () => {
            component.onFileCleared();

            component.startImport();

            expect(importService.postCreateTypeParser).not.toHaveBeenCalled();
        });

        it('ignores a second click while an import is still running', () => {
            component.isImporting = true;

            component.startImport();

            expect(importService.postCreateTypeParser).not.toHaveBeenCalled();
        });

        it('reports the backend message of a failing import', () => {
            importService.postCreateTypeParser.and.returnValue(throwError(() => ({ error: { message: 'Type already exists' } })));

            component.startImport();

            expect(toastService.error).toHaveBeenCalledWith('Type already exists');
            expect(component.importResponse).toBeUndefined();
            expect(component.isImporting).toBeFalse();
            expect(loaderService.hide).toHaveBeenCalled();
        });

        it('falls back to a readable message when the backend sends none', () => {
            importService.postCreateTypeParser.and.returnValue(throwError(() => new Error('network down')));

            component.startImport();

            expect(toastService.error).toHaveBeenCalledWith('The types could not be imported.');
        });

        it('allows a retry after a failed import', () => {
            importService.postCreateTypeParser.and.returnValue(throwError(() => ({ error: { message: 'nope' } })));
            component.startImport();

            importService.postCreateTypeParser.and.returnValue(of({ message: 'ok', success_imports: 2, failed_imports: [] }));
            component.startImport();

            expect(importService.postCreateTypeParser).toHaveBeenCalledTimes(2);
            expect(component.importResponse.success_imports).toBe(2);
        });
    });

    describe('leaving the wizard', () => {
        it('releases the import subscription', () => {
            const unsubscribe = jasmine.createSpy('unsubscribe');
            (component as any).importSubscription = { unsubscribe };

            component.ngOnDestroy();

            expect(unsubscribe).toHaveBeenCalled();
        });
    });
});
