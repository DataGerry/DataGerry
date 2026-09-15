import { CsvMappingComponent } from './csv-mapping.component';

interface MappingControl {
    name: string;
    label: string;
    type: string;
    value?: number;
}

function buildControl(name: string, type = 'field'): MappingControl {
    return { name, label: name.toUpperCase(), type };
}

/**
 * The CSV mapping pre-fills the columns whose header matches a type field, so a file exported from
 * DATAGerry maps itself. Everything the importer cannot resolve has to stay unmapped.
 */
describe('CsvMappingComponent (object import - CSV column mapping)', () => {
    let component: CsvMappingComponent;
    let emitted: unknown[];

    beforeEach(() => {
        component = new CsvMappingComponent();
        emitted = [];
        component.mappingChange.subscribe((mapping) => emitted.push(mapping));
    });

    afterEach(() => component.ngOnDestroy());

    describe('preparing the mapping slots', () => {
        it('creates one empty slot per column of the parsed file', () => {
            component.parsedData = { entry_length: 3 };

            component.ngOnInit();

            expect(component.currentMapping).toEqual([{}, {}, {}]);
        });

        it('creates no slot for a file without columns', () => {
            component.parsedData = { entry_length: 0 };

            component.ngOnInit();

            expect(component.currentMapping).toEqual([]);
        });
    });

    describe('automatic header mapping', () => {
        beforeEach(() => {
            component.parserConfig = { header: true };
            component.parsedData = { header: ['name', 'active'], entry_length: 2 };
        });

        it('maps every column whose header matches a control, at the column position', () => {
            const name = buildControl('name');
            const active = buildControl('active', 'property');
            component.mappingControls = [buildControl('public_id', 'property'), active, name];
            component.ngOnInit();

            component.ngAfterViewInit();

            expect(component.currentMapping[0]).toBe(name);
            expect(component.currentMapping[1]).toBe(active);
            expect(name.value).toBe(0);
            expect(active.value).toBe(1);
        });

        it('leaves controls without a matching header in the available list', () => {
            const description = buildControl('description');
            component.mappingControls = [description];
            component.ngOnInit();

            component.ngAfterViewInit();

            expect(component.mappingControls).toEqual([description]);
            expect(component.currentMapping).toEqual([{}, {}]);
        });

        it('never auto-maps reference controls, the importer cannot resolve them', () => {
            component.parsedData = { header: ['name'], entry_length: 1 };
            const reference = buildControl('name', 'ref');
            component.mappingControls = [reference];
            component.ngOnInit();

            component.ngAfterViewInit();

            expect(component.mappingControls).toEqual([reference]);
            expect(component.currentMapping).toEqual([{}]);
        });

        it('publishes the pre-filled mapping so the summary and the request pick it up', () => {
            component.mappingControls = [buildControl('name')];
            component.ngOnInit();

            component.ngAfterViewInit();

            expect(emitted).toEqual([component.currentMapping]);
        });

        it('maps nothing for a file that has no header row', () => {
            component.parserConfig = { header: false };
            const name = buildControl('name');
            component.mappingControls = [name];
            component.ngOnInit();

            component.ngAfterViewInit();

            expect(component.mappingControls).toEqual([name]);
            expect(emitted).toEqual([]);
        });
    });

    describe('row preview', () => {
        it('starts on the first row', () => {
            expect(component.previewIndex).toBe(0);
        });

        it('follows the selected row and keeps it a number', () => {
            component.previewIndexSelectionForm.get('indexSelection').setValue('2');

            expect(component.previewIndex).toBe(2);
        });

        it('stops following the selection after the step was destroyed', () => {
            component.ngOnDestroy();

            component.previewIndexSelectionForm.get('indexSelection').setValue('4');

            expect(component.previewIndex).toBe(0);
        });
    });
});
