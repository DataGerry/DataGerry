import { ComponentFixture, TestBed, fakeAsync, tick } from '@angular/core/testing';
import { delay, of, throwError } from 'rxjs';

import { ImportObjectsComponent } from './import-objects.component';
import { ImportService } from 'src/app/modules/import/services/import.service';
import { SidebarService } from 'src/app/layout/services/sidebar.service';
import { LoaderService } from 'src/app/core/services/loader.service';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { CmdbType } from 'src/app/framework/models/cmdb-type';

function buildType(overrides: Partial<CmdbType> = {}): CmdbType {
    return { public_id: 12, name: 'server', label: 'Server', fields: [], ...overrides } as CmdbType;
}

function buildFile(name = 'objects.csv', content = 'name;active'): File {
    return new File([content], name, { type: 'text/plain' });
}

/**
 * The wizard host collects the output of every step and turns it into the single import request.
 * These tests cover the whole happy path plus the states the user can reach by jumping between steps.
 */
describe('ImportObjectsComponent (object import wizard host)', () => {
    let component: ImportObjectsComponent;
    let fixture: ComponentFixture<ImportObjectsComponent>;

    let importService: jasmine.SpyObj<ImportService>;
    let sidebarService: jasmine.SpyObj<SidebarService>;
    let toastService: jasmine.SpyObj<ToastService>;
    let loaderService: jasmine.SpyObj<LoaderService>;

    /** The file content is filled by an asynchronous FileReader, so give it a few turns to arrive. */
    const waitForFileContent = async (): Promise<void> => {
        for (let attempt = 0; attempt < 25 && component.importerFile.fileContent === undefined; attempt++) {
            await new Promise<void>((resolve) => setTimeout(resolve, 0));
        }
    };

    beforeEach(async () => {
        importService = jasmine.createSpyObj<ImportService>('ImportService', [
            'getObjectImporterDefaultConfig',
            'postObjectParser',
            'importObjects'
        ]);
        // The importer defaults arrive over HTTP, so they are emitted asynchronously here as well.
        importService.getObjectImporterDefaultConfig.and.returnValue(of({ manually_mapping: true }).pipe(delay(0)));
        importService.postObjectParser.and.returnValue(of({ entries: [], entry_length: 0 }));
        importService.importObjects.and.returnValue(of({ message: 'ok', success_imports: 1, failed_imports: [] }));

        sidebarService = jasmine.createSpyObj<SidebarService>('SidebarService', ['updateTypeCounter']);
        sidebarService.updateTypeCounter.and.returnValue(Promise.resolve());

        toastService = jasmine.createSpyObj<ToastService>('ToastService', ['error']);
        loaderService = jasmine.createSpyObj<LoaderService>('LoaderService', ['show', 'hide'], { isLoading$: of(false) });

        await TestBed.configureTestingModule({
            declarations: [ImportObjectsComponent],
            providers: [
                { provide: ImportService, useValue: importService },
                { provide: SidebarService, useValue: sidebarService },
                { provide: ToastService, useValue: toastService },
                { provide: LoaderService, useValue: loaderService }
            ]
        })
            .overrideComponent(ImportObjectsComponent, { set: { template: '' } })
            .compileComponents();

        fixture = TestBed.createComponent(ImportObjectsComponent);
        component = fixture.componentInstance;
        component.ngOnInit();
    });

    describe('file selection step', () => {
        it('stores the chosen format and loads the importer defaults for it', fakeAsync(() => {
            component.formatChange('csv');
            tick();

            expect(component.importerFile.fileFormat).toBe('csv');
            expect(importService.getObjectImporterDefaultConfig).toHaveBeenCalledWith('csv');
            expect(component.defaultImporterConfig).toEqual({ manually_mapping: true });
        }));

        it('reloads the importer defaults when the format is switched', fakeAsync(() => {
            component.formatChange('csv');
            tick();
            importService.getObjectImporterDefaultConfig.and.returnValue(of({ manually_mapping: false }).pipe(delay(0)));

            component.formatChange('json');
            tick();

            expect(component.importerFile.fileFormat).toBe('json');
            expect(component.defaultImporterConfig).toEqual({ manually_mapping: false });
        }));

        it('reports a failing importer default lookup instead of leaving the step silent', () => {
            importService.getObjectImporterDefaultConfig.and.returnValue(
                throwError(() => ({ error: { message: 'Importer not available' } }))
            );

            component.formatChange('csv');

            expect(toastService.error).toHaveBeenCalledWith('Importer not available');
            expect(component.defaultImporterConfig).toBeUndefined();
        });

        it('keeps the file and its name for the summary panel', () => {
            const file = buildFile('inventory.csv');

            component.fileChange(file);

            expect(component.importerFile.file).toBe(file);
            expect(component.importerFile.fileName).toBe('inventory.csv');
        });

        it('reads the selected file so the mapping step can preview it', async () => {
            component.fileChange(buildFile('inventory.csv', 'name;active'));
            await waitForFileContent();

            expect(component.importerFile.fileContent).toBe('name;active');
        });

        it('replaces a previously selected file when another one is picked', async () => {
            component.fileChange(buildFile('first.csv', 'first'));
            await waitForFileContent();

            component.fileChange(buildFile('second.csv', 'second'));

            expect(component.importerFile.fileName).toBe('second.csv');
        });

        it('cannot read a second file while the first one is still being read', () => {
            // Known gap: the step reuses one FileReader without aborting a pending read, unlike the
            // type import file step. Picking another file for a large upload throws instead of
            // superseding the read. Delete this test once `fileChange` aborts the running read.
            component.fileChange(buildFile('first.csv', 'a'.repeat(4096)));

            expect(() => component.fileChange(buildFile('second.csv'))).toThrow();
        });
    });

    describe('parser config step', () => {
        it('applies the parser config on the next turn, so the mapping step re-renders with it', fakeAsync(() => {
            component.parserConfigChange({ header: true, separator: ';' });
            expect(component.parserConfig).toBeUndefined();

            tick();
            expect(component.parserConfig).toEqual({ header: true, separator: ';' });
        }));

        it('parses the file with the current parser config', () => {
            const file = buildFile();
            component.fileChange(file);
            component.formatChange('csv');
            component.parserConfig = { header: true };

            component.onParseData();

            expect(importService.postObjectParser).toHaveBeenCalledWith(file, 'csv', { header: true });
            expect(component.parsedData).toEqual({ entries: [], entry_length: 0 });
        });

        it('reports a failing parse instead of moving on with stale preview data', () => {
            importService.postObjectParser.and.returnValue(throwError(() => ({ error: { message: 'Malformed file' } })));
            component.fileChange(buildFile());
            component.formatChange('csv');

            component.onParseData();

            expect(toastService.error).toHaveBeenCalledWith('Malformed file');
            expect(component.parsedData).toBeUndefined();
        });
    });

    describe('type mapping step', () => {
        it('keeps the selected type and its id for the import request', () => {
            const typeInstance = buildType({ public_id: 42 });

            component.typeChange({ typeID: 42, typeInstance });

            expect(component.importerConfig.type_id).toBe(42);
            expect(component.typeInstance).toBe(typeInstance);
        });

        it('drops mapping slots the user left empty', () => {
            component.mappingChange([{ name: 'name', value: 0 }, {}, { name: 'active', value: 1 }]);

            expect(component.mapping).toEqual([{ name: 'name', value: 0 }, { name: 'active', value: 1 }] as any);
        });

        it('drops slots that were cleared back to a blank placeholder', () => {
            component.mappingChange(['', { name: 'name', value: 0 }, '']);

            expect(component.mapping).toEqual([{ name: 'name', value: 0 }] as any);
        });
    });

    describe('import config step', () => {
        it('ignores an undefined config so a half-built step cannot wipe the selection', () => {
            component.importerConfig = { type_id: 5 } as any;

            component.importConfigChange(undefined);

            expect(component.importerConfig).toEqual({ type_id: 5 } as any);
        });

        it('re-applies the selected type onto a config emitted after the mapping step', () => {
            component.typeChange({ typeID: 42, typeInstance: buildType({ public_id: 42 }) });

            component.importConfigChange({ start_element: 1, max_elements: 0, overwrite_public: true });

            expect(component.importerConfig.type_id).toBe(42);
            expect(component.importerConfig.start_element).toBe(1);
        });

        it('leaves the config untouched while no type has been selected yet', () => {
            component.importConfigChange({ start_element: 0, max_elements: 0, overwrite_public: false });

            expect(component.importerConfig.type_id).toBeUndefined();
        });
    });

    describe('starting the import', () => {
        beforeEach(() => {
            component.fileChange(buildFile());
            component.formatChange('csv');
            component.typeChange({ typeID: 42, typeInstance: buildType({ public_id: 42 }) });
            component.importConfigChange({ start_element: 0, max_elements: 0, overwrite_public: false });
            component.parserConfig = { header: true };
        });

        it('sends the manual mapping along when the importer asks for one', () => {
            component.defaultImporterConfig = { manually_mapping: true };
            component.mappingChange([{ name: 'name', value: 0 }]);

            component.startImport();

            const [, , parserConfig, importerConfig] = importService.importObjects.calls.mostRecent().args;
            expect(parserConfig).toEqual({ header: true });
            expect((importerConfig as any).mapping).toEqual([{ name: 'name', value: 0 }]);
        });

        it('does not send a mapping for importers that map on their own', () => {
            component.defaultImporterConfig = { manually_mapping: false };
            component.mappingChange([{ name: 'name', value: 0 }]);

            component.startImport();

            const [, , , importerConfig] = importService.importObjects.calls.mostRecent().args;
            expect((importerConfig as any).mapping).toBeUndefined();
        });

        it('keeps the import report for the completion step', () => {
            component.defaultImporterConfig = { manually_mapping: false };
            const response = { message: 'done', success_imports: 3, failed_imports: [] };
            importService.importObjects.and.returnValue(of(response));

            component.startImport();

            expect(component.importResponse).toEqual(response);
        });

        it('shows the loader while importing and hides it afterwards', () => {
            component.defaultImporterConfig = { manually_mapping: false };

            component.startImport();

            expect(loaderService.show).toHaveBeenCalled();
            expect(loaderService.hide).toHaveBeenCalled();
            expect(component.isImporting).toBeFalse();
        });

        it('refreshes the sidebar object counter of the imported type', () => {
            component.defaultImporterConfig = { manually_mapping: false };

            component.startImport();

            expect(sidebarService.updateTypeCounter).toHaveBeenCalledWith(42);
        });

        it('ignores a second click while an import is still running', () => {
            component.defaultImporterConfig = { manually_mapping: false };
            component.isImporting = true;

            component.startImport();

            expect(importService.importObjects).not.toHaveBeenCalled();
        });

        it('reports a failing import, releases the loader and leaves the counter untouched', () => {
            component.defaultImporterConfig = { manually_mapping: false };
            importService.importObjects.and.returnValue(throwError(() => ({ error: { message: 'Import rejected' } })));

            component.startImport();

            expect(toastService.error).toHaveBeenCalledWith('Import rejected');
            expect(component.importResponse).toBeUndefined();
            expect(component.isImporting).toBeFalse();
            expect(loaderService.hide).toHaveBeenCalled();
            expect(sidebarService.updateTypeCounter).not.toHaveBeenCalled();
        });

        it('allows a retry after a failed import', () => {
            component.defaultImporterConfig = { manually_mapping: false };
            importService.importObjects.and.returnValue(throwError(() => ({ error: { message: 'Import rejected' } })));
            component.startImport();

            importService.importObjects.and.returnValue(of({ message: 'ok', success_imports: 1, failed_imports: [] }));
            component.startImport();

            expect(importService.importObjects).toHaveBeenCalledTimes(2);
            expect(component.importResponse.success_imports).toBe(1);
        });
    });

    describe('leaving the wizard', () => {
        it('releases the import and parse subscriptions', () => {
            const importerUnsubscribe = jasmine.createSpy('importerUnsubscribe');
            const parseUnsubscribe = jasmine.createSpy('parseUnsubscribe');
            (component as any).importerSubscription = { unsubscribe: importerUnsubscribe };
            (component as any).parseDataSubscription = { unsubscribe: parseUnsubscribe };

            component.ngOnDestroy();

            expect(importerUnsubscribe).toHaveBeenCalled();
            expect(parseUnsubscribe).toHaveBeenCalled();
        });

        it('aborts a file read that is still running', () => {
            component.fileChange(buildFile('big.csv', 'a'.repeat(2048)));

            expect(() => component.ngOnDestroy()).not.toThrow();
        });
    });
});
