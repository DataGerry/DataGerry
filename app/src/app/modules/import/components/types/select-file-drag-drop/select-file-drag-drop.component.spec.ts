import { firstValueFrom } from 'rxjs';

import { ParsedTypeFile, SelectFileDragDropComponent } from './select-file-drag-drop.component';

function buildFile(content: string, name = 'types.json'): File {
    return new File([content], name, { type: 'application/json' });
}

/**
 * The file step decodes the upload in the browser, so the review step can show what is inside before
 * anything is sent. Every way a file can be unusable has to end in a readable message, not a crash.
 */
describe('SelectFileDragDropComponent (type import - file step)', () => {
    let component: SelectFileDragDropComponent;

    /** Picks a file and resolves once it was decoded successfully. */
    const selectValidFile = (content: string, name?: string): Promise<ParsedTypeFile> => {
        const parsed = firstValueFrom(component.fileParsed);
        component.onFileSelected(buildFile(content, name));
        return parsed;
    };

    /** Picks a file and resolves once it was refused. */
    const selectUnusableFile = (content: string, name?: string): Promise<void> => {
        const cleared = firstValueFrom(component.fileCleared);
        component.onFileSelected(buildFile(content, name));
        return cleared;
    };

    beforeEach(() => component = new SelectFileDragDropComponent());

    afterEach(() => component.ngOnDestroy());

    describe('a usable type export', () => {
        it('publishes the file together with the decoded types', async () => {
            const parsed = await selectValidFile('[{"name":"server"},{"name":"router"}]', 'export.json');

            expect(parsed.file.name).toBe('export.json');
            expect(parsed.types.length).toBe(2);
        });

        it('lets the user continue to the review step', async () => {
            await selectValidFile('[{"name":"server"}]');

            expect(component.canContinue).toBeTrue();
            expect(component.parseError).toBe('');
            expect(component.isParsing).toBeFalse();
        });

        it('reports that it is working while the file is being read', () => {
            component.onFileSelected(buildFile('[{"name":"server"}]'));

            expect(component.isParsing).toBeTrue();
            expect(component.canContinue).toBeFalse();
        });

        it('replaces the previously decoded upload', async () => {
            await selectValidFile('[{"name":"server"}]');

            const parsed = await selectValidFile('[{"name":"router"},{"name":"switch"}]');

            expect(parsed.types.length).toBe(2);
            expect(component.parsedTypes.length).toBe(2);
        });
    });

    describe('an unusable file', () => {
        it('explains that the file is not JSON', async () => {
            await selectUnusableFile('name;label\nserver;Server', 'types.csv');

            expect(component.parseError).toBe('This file is not valid JSON. Please upload a type export created by DATAGerry.');
            expect(component.parsedTypes).toEqual([]);
            expect(component.canContinue).toBeFalse();
        });

        it('explains that a single type object is not a list', async () => {
            await selectUnusableFile('{"name":"server"}');

            expect(component.parseError).toBe('The file must contain a JSON list of types.');
        });

        it('explains that a JSON primitive is not a list', async () => {
            await selectUnusableFile('42');

            expect(component.parseError).toBe('The file must contain a JSON list of types.');
        });

        it('explains that an empty list carries nothing to import', async () => {
            await selectUnusableFile('[]');

            expect(component.parseError).toBe('The file does not contain any types.');
        });

        it('explains that an empty file cannot be read as JSON', async () => {
            await selectUnusableFile('');

            expect(component.parseError).toBe('This file is not valid JSON. Please upload a type export created by DATAGerry.');
        });

        it('clears the message once a usable file is picked', async () => {
            await selectUnusableFile('not json');

            await selectValidFile('[{"name":"server"}]');

            expect(component.parseError).toBe('');
            expect(component.canContinue).toBeTrue();
        });

        it('drops a previously decoded upload, so the step cannot continue with stale types', async () => {
            await selectValidFile('[{"name":"server"}]');

            await selectUnusableFile('not json');

            expect(component.parsedTypes).toEqual([]);
            expect(component.canContinue).toBeFalse();
        });
    });

    describe('removing the file', () => {
        it('resets the state and tells the wizard host', async () => {
            await selectValidFile('[{"name":"server"}]');
            const cleared = firstValueFrom(component.fileCleared);

            component.onFileCleared();
            await cleared;

            expect(component.parsedTypes).toEqual([]);
            expect(component.parseError).toBe('');
            expect(component.isParsing).toBeFalse();
            expect(component.canContinue).toBeFalse();
        });

        it('treats a file refused by the dropzone filter like a removal', async () => {
            await selectValidFile('[{"name":"server"}]');
            const cleared = firstValueFrom(component.fileCleared);

            component.onFileRejected();
            await cleared;

            expect(component.parsedTypes).toEqual([]);
            expect(component.canContinue).toBeFalse();
        });
    });

    describe('leaving the step', () => {
        it('aborts a read that is still running', () => {
            component.onFileSelected(buildFile(`[${ '{"name":"server"},'.repeat(500) }{"name":"last"}]`));

            expect(() => component.ngOnDestroy()).not.toThrow();
        });
    });
});
