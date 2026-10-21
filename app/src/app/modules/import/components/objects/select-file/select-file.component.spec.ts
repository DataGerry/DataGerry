import { ComponentFixture, TestBed } from '@angular/core/testing';
import { of } from 'rxjs';

import { SelectFileComponent } from './select-file.component';
import { ImportService } from '../../../services/import.service';
import { LoaderService } from 'src/app/core/services/loader.service';

function buildFile(name = 'objects.csv'): File {
    return new File(['name;active'], name, { type: 'text/plain' });
}

/**
 * The first wizard step decides which importer is used and which file it gets. The format has to be
 * picked first, and a file must never survive a format switch — these tests pin both rules down.
 */
describe('SelectFileComponent (object import - file step)', () => {
    let component: SelectFileComponent;
    let fixture: ComponentFixture<SelectFileComponent>;

    let importService: jasmine.SpyObj<ImportService>;
    let loaderService: jasmine.SpyObj<LoaderService>;

    beforeEach(async () => {
        importService = jasmine.createSpyObj<ImportService>('ImportService', ['getObjectImporters']);
        importService.getObjectImporters.and.returnValue(of([{ name: 'csv' }, { name: 'json' }] as any));

        loaderService = jasmine.createSpyObj<LoaderService>('LoaderService', ['show', 'hide'], { isLoading$: of(false) });

        await TestBed.configureTestingModule({
            declarations: [SelectFileComponent],
            providers: [
                { provide: ImportService, useValue: importService },
                { provide: LoaderService, useValue: loaderService }
            ]
        })
            .overrideComponent(SelectFileComponent, { set: { template: '' } })
            .compileComponents();

        fixture = TestBed.createComponent(SelectFileComponent);
        component = fixture.componentInstance;
    });

    describe('available formats', () => {
        it('offers every registered importer with an upper case label', () => {
            component.ngOnInit();

            expect(component.formatOptions).toEqual([
                { label: 'CSV', value: 'csv' },
                { label: 'JSON', value: 'json' }
            ]);
        });

        it('shows no format when the backend answers without any importer', () => {
            importService.getObjectImporters.and.returnValue(of(null as any));

            component.ngOnInit();

            expect(component.formatOptions).toEqual([]);
        });

        it('survives an importer entry without a name instead of breaking the step', () => {
            importService.getObjectImporters.and.returnValue(of([{}] as any));

            component.ngOnInit();

            expect(component.formatOptions).toEqual([{ label: '', value: undefined }]);
        });

        it('shows the loader while the importers are fetched', () => {
            component.ngOnInit();

            expect(loaderService.show).toHaveBeenCalled();
            expect(loaderService.hide).toHaveBeenCalled();
        });
    });

    describe('format before file', () => {
        beforeEach(() => component.ngOnInit());

        it('keeps the file selection disabled until a format is chosen', () => {
            expect(component.file.disabled).toBeTrue();
        });

        it('enables the file selection once a format is chosen', () => {
            component.fileFormat.setValue('csv');

            expect(component.file.enabled).toBeTrue();
        });

        it('disables the file selection again when the format is cleared', () => {
            component.fileFormat.setValue('csv');
            component.fileFormat.setValue('');

            expect(component.file.disabled).toBeTrue();
            expect(component.selectedFileFormat).toBe('');
        });

        it('publishes the chosen format and the matching file extension', () => {
            const emitted: string[] = [];
            component.formatChange.subscribe((format) => emitted.push(format));

            component.fileFormat.setValue('csv');

            expect(emitted).toEqual(['csv']);
            expect(component.selectedFileFormat).toBe('.csv');
        });

        it('stays invalid until both a format and a file are present', () => {
            expect(component.fileForm.valid).toBeFalse();

            component.fileFormat.setValue('csv');
            expect(component.fileForm.valid).toBeFalse();

            component.file.setValue(buildFile());
            expect(component.fileForm.valid).toBeTrue();
        });
    });

    describe('file selection', () => {
        beforeEach(() => component.ngOnInit());

        it('publishes the picked file', () => {
            const emitted: File[] = [];
            component.fileChange.subscribe((file) => emitted.push(file));
            component.fileFormat.setValue('csv');

            const file = buildFile();
            component.file.setValue(file);

            expect(emitted).toEqual([file]);
        });

        it('does not publish anything when the file is cleared', () => {
            const emitted: File[] = [];
            component.fileChange.subscribe((file) => emitted.push(file));
            component.fileFormat.setValue('csv');

            component.file.setValue(null);

            expect(emitted).toEqual([]);
        });

        it('drops a file that was picked for the previous format', () => {
            const emitted: File[] = [];
            component.fileChange.subscribe((file) => emitted.push(file));
            component.fileFormat.setValue('csv');
            component.file.setValue(buildFile('objects.csv'));

            component.fileFormat.setValue('json');

            expect(component.file.value).toBeNull();
            expect(emitted.length).toBe(1);
        });
    });

    describe('leaving the step', () => {
        it('stops publishing after the component was destroyed', () => {
            component.ngOnInit();
            const emitted: string[] = [];
            component.formatChange.subscribe((format) => emitted.push(format));

            component.ngOnDestroy();
            component.fileFormat.setValue('csv');

            expect(emitted).toEqual([]);
        });
    });
});
