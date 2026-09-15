import { of } from 'rxjs';

import { ApiCallService } from '../../../services/api-call.service';
import { ImportService, httpImportFileOptions } from './import.service';
import { ImporterConfig } from '../models/import-object.models';

function buildFile(name = 'objects.csv', content = 'a;b'): File {
    return new File([content], name, { type: 'text/plain' });
}

function buildImporterConfig(overrides: Partial<ImporterConfig> = {}): ImporterConfig {
    return { mapping: {}, type_id: 7, start_element: 0, max_elements: 0, overwrite_public: false, ...overrides };
}

/**
 * The import endpoints are the contract between the wizards and the backend. These tests lock down the
 * routes, the multipart payload keys and how empty (204) answers are translated for the UI.
 */
describe('ImportService (import endpoints)', () => {
    let service: ImportService;
    let api: jasmine.SpyObj<ApiCallService>;

    /** Reads back the multipart body the service handed to the API layer. */
    const postedForm = (callIndex = 0): FormData => api.callPost.calls.argsFor(callIndex)[1] as FormData;

    beforeEach(() => {
        api = jasmine.createSpyObj<ApiCallService>('ApiCallService', ['callGet', 'callPost']);
        api.callGet.and.returnValue(of({ status: 200, body: {} }));
        api.callPost.and.returnValue(of({ status: 200, body: {} }));

        service = new ImportService(api);
    });

    describe('object import', () => {
        it('posts the file, format and both configs to the object import route', () => {
            const file = buildFile();
            const parserConfig = { header: true, separator: ';' };
            const importerConfig = buildImporterConfig({ start_element: 2 });

            service.importObjects(file, 'csv', parserConfig, importerConfig).subscribe();

            expect(api.callPost).toHaveBeenCalledWith('import/object/', jasmine.any(FormData), httpImportFileOptions);

            const form = postedForm();
            expect((form.get('file') as File).name).toBe('objects.csv');
            expect(form.get('file_format')).toBe('csv');
            expect(JSON.parse(form.get('parser_config') as string)).toEqual(parserConfig);
            expect(JSON.parse(form.get('importer_config') as string)).toEqual(importerConfig as unknown as object);
        });

        it('unwraps the response body of the import call', () => {
            const body = { message: 'ok', success_imports: 3, failed_imports: [] };
            api.callPost.and.returnValue(of({ status: 200, body }));

            let result: unknown;
            service.importObjects(buildFile(), 'csv', {}, buildImporterConfig()).subscribe((response) => result = response);

            expect(result).toBe(body);
        });

        it('posts to the parse route without the importer config', () => {
            service.postObjectParser(buildFile(), 'json', { indent: 2 }).subscribe();

            expect(api.callPost).toHaveBeenCalledWith('import/object/parse/', jasmine.any(FormData), httpImportFileOptions);

            const form = postedForm();
            expect(form.get('file_format')).toBe('json');
            expect(JSON.parse(form.get('parser_config') as string)).toEqual({ indent: 2 });
            expect(form.get('importer_config')).toBeNull();
        });
    });

    describe('object importer / parser defaults', () => {
        it('requests the importer default config for the given file type', () => {
            service.getObjectImporterDefaultConfig('csv').subscribe();

            expect(api.callGet).toHaveBeenCalledWith('import/object/importer/config/csv/');
        });

        it('turns an empty importer config answer into an empty object', () => {
            api.callGet.and.returnValue(of({ status: 204, body: null }));

            let result: unknown;
            service.getObjectImporterDefaultConfig('csv').subscribe((config) => result = config);

            expect(result).toEqual({});
        });

        it('requests the parser default config for the given file type', () => {
            service.getObjectParserDefaultConfig('json').subscribe();

            expect(api.callGet).toHaveBeenCalledWith('import/object/parser/default/json/');
        });

        it('turns an empty parser config answer into an empty object', () => {
            api.callGet.and.returnValue(of({ status: 204, body: null }));

            let result: unknown;
            service.getObjectParserDefaultConfig('json').subscribe((config) => result = config);

            expect(result).toEqual({});
        });

        it('returns the available importers', () => {
            const importers = [{ name: 'csv' }, { name: 'json' }] as unknown as string[];
            api.callGet.and.returnValue(of({ status: 200, body: importers }));

            let result: unknown;
            service.getObjectImporters().subscribe((list) => result = list);

            expect(api.callGet).toHaveBeenCalledWith('import/object/importer/');
            expect(result).toBe(importers);
        });

        it('returns an empty list when no importer is registered', () => {
            api.callGet.and.returnValue(of({ status: 204, body: null }));

            let result: unknown;
            service.getObjectImporters().subscribe((list) => result = list);

            expect(result).toEqual([]);
        });
    });

    describe('type import', () => {
        it('posts new types to the create route', () => {
            const formData = new FormData();
            formData.append('uploadFile', '[]');

            service.postCreateTypeParser(formData).subscribe();

            expect(api.callPost).toHaveBeenCalledWith('import/type/create/', formData, httpImportFileOptions);
        });

        it('posts existing types to the update route', () => {
            const formData = new FormData();
            formData.append('uploadFile', '[]');

            service.postUpdateTypeParser(formData).subscribe();

            expect(api.callPost).toHaveBeenCalledWith('import/type/update/', formData, httpImportFileOptions);
        });

        it('unwraps the response body of the type import', () => {
            const body = { message: 'ok', success_imports: 2, failed_imports: [] };
            api.callPost.and.returnValue(of({ status: 200, body }));

            let result: unknown;
            service.postCreateTypeParser(new FormData()).subscribe((response) => result = response);

            expect(result).toBe(body);
        });
    });

    describe('ISMS importers', () => {
        const cases: { label: string; route: string; call: (file: File) => void }[] = [
            { label: 'threat', route: 'isms/importer/threat', call: (file) => service.importThreatFile(file).subscribe() },
            { label: 'risk', route: 'isms/importer/risk', call: (file) => service.importRiskFile(file).subscribe() },
            {
                label: 'control measure',
                route: 'isms/importer/control_measure',
                call: (file) => service.importControlMeasureFile(file).subscribe()
            },
            {
                label: 'vulnerability',
                route: 'isms/importer/vulnerability',
                call: (file) => service.importVulnerabilityFile(file).subscribe()
            }
        ];

        cases.forEach(({ label, route, call }) => {
            it(`posts the ${ label } file to its own route including the file name`, () => {
                const file = buildFile(`${ label }.xlsx`);

                call(file);

                expect(api.callPost).toHaveBeenCalledWith(route, jasmine.any(FormData), httpImportFileOptions);
                expect((postedForm().get('file') as File).name).toBe(`${ label }.xlsx`);
            });
        });
    });
});
