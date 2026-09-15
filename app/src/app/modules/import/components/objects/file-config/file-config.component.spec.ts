import { ComponentFactoryResolver, SimpleChange, SimpleChanges } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { UntypedFormControl } from '@angular/forms';
import { of } from 'rxjs';

import { FileConfigComponent, configComponents } from './file-config.component';
import { CsvConfigComponent } from '../csv-config/csv-config.component';
import { JsonConfigComponent } from '../json-config/json-config.component';
import { ImportService } from '../../../services/import.service';
import { LoaderService } from 'src/app/core/services/loader.service';

function formatChange(currentValue: string, firstChange = false): SimpleChanges {
    return { fileFormat: new SimpleChange(firstChange ? undefined : 'json', currentValue, firstChange) };
}

/**
 * The parser step hosts the format specific config form. Switching the format has to throw the previous
 * form away, fetch the defaults of the new parser and re-wire the change stream to the new form.
 */
describe('FileConfigComponent (object import - parser config step)', () => {
    let component: FileConfigComponent;
    let fixture: ComponentFixture<FileConfigComponent>;

    let importService: jasmine.SpyObj<ImportService>;
    let loaderService: jasmine.SpyObj<LoaderService>;
    let resolver: jasmine.SpyObj<ComponentFactoryResolver>;
    let container: { clear: jasmine.Spy; createComponent: jasmine.Spy };
    let createdInstance: Record<string, unknown>;

    /** Runs the format switch the wizard triggers when the user picks another importer. */
    const switchFormatTo = (format: string) => {
        component.fileFormat = format;
        component.ngOnChanges(formatChange(format));
    };

    beforeEach(async () => {
        importService = jasmine.createSpyObj<ImportService>('ImportService', ['getObjectParserDefaultConfig']);
        importService.getObjectParserDefaultConfig.and.returnValue(of({ header: true, separator: ';' }));

        loaderService = jasmine.createSpyObj<LoaderService>('LoaderService', ['show', 'hide'], { isLoading$: of(false) });

        resolver = jasmine.createSpyObj<ComponentFactoryResolver>('ComponentFactoryResolver', ['resolveComponentFactory']);
        resolver.resolveComponentFactory.and.returnValue({} as any);

        createdInstance = {};
        container = {
            clear: jasmine.createSpy('clear'),
            createComponent: jasmine.createSpy('createComponent').and.returnValue({ instance: createdInstance })
        };

        await TestBed.configureTestingModule({
            declarations: [FileConfigComponent],
            providers: [
                { provide: ImportService, useValue: importService },
                { provide: LoaderService, useValue: loaderService },
                { provide: ComponentFactoryResolver, useValue: resolver }
            ]
        })
            .overrideComponent(FileConfigComponent, { set: { template: '' } })
            .compileComponents();

        fixture = TestBed.createComponent(FileConfigComponent);
        component = fixture.componentInstance;
        component.fileConfig = container;
    });

    describe('config component registry', () => {
        it('maps each supported file format to its config component', () => {
            expect(configComponents['csv']).toBe(CsvConfigComponent);
            expect(configComponents['json']).toBe(JsonConfigComponent);
        });
    });

    describe('entering the step', () => {
        it('starts with an empty host so no stale config form is shown', () => {
            component.ngOnInit();

            expect(container.clear).toHaveBeenCalled();
        });

        it('publishes the parser config whenever the hosted form changes', () => {
            const emitted: unknown[] = [];
            component.configChange.subscribe((config) => emitted.push(config));
            component.ngOnInit();

            component.configForm.addControl('header', new UntypedFormControl(true));

            expect(emitted).toEqual([{ header: true }]);
        });
    });

    describe('switching the file format', () => {
        beforeEach(() => component.ngOnInit());

        it('ignores the initial binding, the format step has not been left yet', () => {
            component.fileFormat = 'json';
            component.ngOnChanges(formatChange('json', true));

            expect(importService.getObjectParserDefaultConfig).not.toHaveBeenCalled();
            expect(container.createComponent).not.toHaveBeenCalled();
        });

        it('rebuilds the config form for the newly chosen format', () => {
            const previousForm = component.configForm;

            switchFormatTo('csv');

            expect(container.clear).toHaveBeenCalled();
            expect(component.configForm).not.toBe(previousForm);
            expect(resolver.resolveComponentFactory).toHaveBeenCalledWith(CsvConfigComponent);
            expect(container.createComponent).toHaveBeenCalled();
        });

        it('hands the fetched parser defaults and the form down to the config component', () => {
            switchFormatTo('csv');

            expect(importService.getObjectParserDefaultConfig).toHaveBeenCalledWith('csv');
            expect(createdInstance['configForm']).toBe(component.configForm);
            expect(createdInstance['defaultParserConfig']).toEqual({ header: true, separator: ';' });
        });

        it('shows the loader while the parser defaults are fetched', () => {
            switchFormatTo('csv');

            expect(loaderService.show).toHaveBeenCalled();
            expect(loaderService.hide).toHaveBeenCalled();
        });

        it('publishes changes made on the rebuilt form', () => {
            switchFormatTo('csv');
            const emitted: unknown[] = [];
            component.configChange.subscribe((config) => emitted.push(config));

            component.configForm.addControl('separator', new UntypedFormControl(';'));

            expect(emitted).toEqual([{ separator: ';' }]);
        });

        it('still publishes changes made on the form that was thrown away', () => {
            // Known gap: `resetConfigSub` overwrites the stored subscription without unsubscribing the
            // previous one, so every format switch leaks a subscription and the abandoned form keeps
            // pushing its config to the wizard host. Invert this test once the old sub is released.
            const abandonedForm = component.configForm;
            switchFormatTo('csv');
            const emitted: unknown[] = [];
            component.configChange.subscribe((config) => emitted.push(config));

            abandonedForm.addControl('header', new UntypedFormControl(true));

            expect(emitted).toEqual([{}]);
        });

        it('also rebuilds when the format is cleared - there is no config component for it', () => {
            // Documents current behaviour: the step does not guard against an empty format, so it asks
            // the registry for a component that does not exist. Worth a guard if the format can be reset.
            switchFormatTo('');

            expect(resolver.resolveComponentFactory).toHaveBeenCalledWith(undefined as any);
        });
    });

    describe('leaving the step', () => {
        it('stops publishing after the component was destroyed', () => {
            component.ngOnInit();
            const emitted: unknown[] = [];
            component.configChange.subscribe((config) => emitted.push(config));

            component.ngOnDestroy();
            component.configForm.addControl('header', new UntypedFormControl(true));

            expect(emitted).toEqual([]);
        });
    });
});
