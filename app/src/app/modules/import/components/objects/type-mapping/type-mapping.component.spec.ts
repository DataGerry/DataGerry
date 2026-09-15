import { ComponentFactoryResolver, SimpleChange, SimpleChanges } from '@angular/core';
import { ComponentFixture, TestBed, fakeAsync, tick } from '@angular/core/testing';
import { delay, of } from 'rxjs';

import { TypeMappingComponent, mappingComponents, unsupportedImportFieldTypes } from './type-mapping.component';
import { JsonMappingComponent } from '../json-mapping/json-mapping.component';
import { CsvMappingComponent } from '../csv-mapping/csv-mapping.component';
import { TypeService } from 'src/app/framework/services/type.service';
import { LoaderService } from 'src/app/core/services/loader.service';
import { CmdbType } from 'src/app/framework/models/cmdb-type';

function buildType(overrides: Partial<CmdbType> = {}): CmdbType {
    return { public_id: 42, name: 'server', label: 'Server', fields: [], ...overrides } as CmdbType;
}

function parsedDataChange(currentValue: unknown, firstChange = false): SimpleChanges {
    return { parsedData: new SimpleChange(undefined, currentValue, firstChange) };
}

/**
 * The mapping step decides which type the file is imported into and builds the list of mappable
 * controls from it. It also has to warn about the field types whose references are not imported.
 */
describe('TypeMappingComponent (object import - type mapping step)', () => {
    let component: TypeMappingComponent;
    let fixture: ComponentFixture<TypeMappingComponent>;

    let typeService: jasmine.SpyObj<TypeService<CmdbType>>;
    let loaderService: jasmine.SpyObj<LoaderService>;
    let resolver: jasmine.SpyObj<ComponentFactoryResolver>;
    let createdInstance: Record<string, unknown>;

    beforeEach(async () => {
        typeService = jasmine.createSpyObj<TypeService<CmdbType>>('TypeService', ['getTypeList', 'getType']);
        typeService.getTypeList.and.returnValue(of([]));
        typeService.getType.and.returnValue(of(buildType()));

        loaderService = jasmine.createSpyObj<LoaderService>('LoaderService', ['show', 'hide'], { isLoading$: of(false) });

        resolver = jasmine.createSpyObj<ComponentFactoryResolver>('ComponentFactoryResolver', ['resolveComponentFactory']);
        resolver.resolveComponentFactory.and.returnValue({} as any);

        await TestBed.configureTestingModule({
            declarations: [TypeMappingComponent],
            providers: [
                { provide: TypeService, useValue: typeService },
                { provide: LoaderService, useValue: loaderService },
                { provide: ComponentFactoryResolver, useValue: resolver }
            ]
        })
            .overrideComponent(TypeMappingComponent, { set: { template: '' } })
            .compileComponents();

        fixture = TestBed.createComponent(TypeMappingComponent);
        component = fixture.componentInstance;
        component.fileFormat = 'csv';

        createdInstance = {};
        component.mappingContainer = {
            clear: jasmine.createSpy('clear'),
            createComponent: jasmine.createSpy('createComponent').and.returnValue({ instance: createdInstance })
        };
    });

    describe('mapping component registry', () => {
        it('maps each supported file format to its mapping component', () => {
            expect(mappingComponents['csv']).toBe(CsvMappingComponent);
            expect(mappingComponents['json']).toBe(JsonMappingComponent);
        });
    });

    describe('selectable types', () => {
        it('only offers types the user may read, create and update', () => {
            component.ngOnInit();

            expect(typeService.getTypeList).toHaveBeenCalledWith(['READ', 'CREATE', 'UPDATE'] as any);
        });

        it('keeps the returned types for the selection', () => {
            const types = [buildType({ public_id: 1 }), buildType({ public_id: 2 })];
            typeService.getTypeList.and.returnValue(of(types));

            component.ngOnInit();

            expect(component.typeList).toBe(types);
        });

        it('preselects the only type the user has access to', fakeAsync(() => {
            typeService.getTypeList.and.returnValue(of([buildType({ public_id: 7 })]).pipe(delay(0)));
            typeService.getType.and.returnValue(of(buildType({ public_id: 7 })));
            const emitted: unknown[] = [];
            component.ngOnInit();
            component.typeChange.subscribe((change) => emitted.push(change));

            tick();

            expect(component.configForm.get('typeID').value).toBe(7);
            expect(emitted).toEqual([{ typeID: 7, typeInstance: jasmine.any(CmdbType) }]);
        }));

        it('does not preselect anything when several types are available', fakeAsync(() => {
            typeService.getTypeList.and.returnValue(of([buildType({ public_id: 1 }), buildType({ public_id: 2 })]).pipe(delay(0)));
            component.ngOnInit();

            tick();

            expect(component.configForm.get('typeID').value).toBeNull();
            expect(typeService.getType).not.toHaveBeenCalled();
        }));

        it('shows the loader while the types are fetched', () => {
            component.ngOnInit();

            expect(loaderService.show).toHaveBeenCalled();
            expect(loaderService.hide).toHaveBeenCalled();
        });
    });

    describe('choosing a type', () => {
        beforeEach(() => component.ngOnInit());

        it('loads the full type and publishes it to the wizard host', () => {
            const emitted: any[] = [];
            component.typeChange.subscribe((change) => emitted.push(change));

            component.configForm.get('typeID').patchValue('42');

            expect(typeService.getType).toHaveBeenCalledWith(42);
            expect(emitted.length).toBe(1);
            expect(emitted[0].typeID).toBe(42);
            expect(emitted[0].typeInstance instanceof CmdbType).toBeTrue();
        });

        it('rebuilds the mapping for the newly chosen type', () => {
            typeService.getType.and.returnValue(of(buildType({ fields: [{ name: 'hostname', label: 'Hostname', type: 'text' }] })));

            component.configForm.get('typeID').patchValue(42);

            expect(component.mappingControls.map((control: any) => control.name)).toEqual(['public_id', 'active', 'hostname']);
        });
    });

    describe('mappable controls', () => {
        it('always offers the object properties before the type fields', () => {
            component.typeInstance = buildType({
                fields: [{ name: 'hostname', label: 'Hostname', type: 'text' }]
            });

            component.initMapping();

            expect(component.mappingControls).toEqual([
                { name: 'public_id', label: 'Public ID', type: 'property' },
                { name: 'active', label: 'Active', type: 'property' },
                { name: 'hostname', label: 'Hostname', type: 'field' }
            ]);
        });

        it('offers only the object properties while no type is selected', () => {
            component.typeInstance = undefined;

            component.initMapping();

            expect(component.mappingControls.map((control: any) => control.name)).toEqual(['public_id', 'active']);
        });

        it('discards the mapping of the previously selected type', () => {
            component.typeInstance = buildType({ fields: [{ name: 'hostname', label: 'Hostname', type: 'text' }] });
            component.initMapping();
            component.currentMapping = [{ name: 'hostname' }];

            component.typeInstance = buildType({ fields: [{ name: 'serial', label: 'Serial', type: 'text' }] });
            component.initMapping();

            expect(component.currentMapping).toEqual([]);
            expect(component.mappingControls.map((control: any) => control.name)).toEqual(['public_id', 'active', 'serial']);
        });

        it('hands the parsed file and the mapping state to the format specific component', () => {
            component.parserConfig = { header: true };
            component.parsedData = { header: ['hostname'], entry_length: 1 };
            component.typeInstance = buildType();

            component.initMapping();

            expect(resolver.resolveComponentFactory).toHaveBeenCalledWith(CsvMappingComponent);
            expect(createdInstance['parserConfig']).toBe(component.parserConfig);
            expect(createdInstance['parsedData']).toBe(component.parsedData);
            expect(createdInstance['mappingControls']).toBe(component.mappingControls);
            expect(createdInstance['currentMapping']).toBe(component.currentMapping);
            expect(createdInstance['mappingChange']).toBe(component.mappingChange);
        });
    });

    describe('unsupported field warning', () => {
        it('names the three field kinds whose references are not imported', () => {
            expect(unsupportedImportFieldTypes).toEqual({
                'ref': 'Reference',
                'location': 'Location',
                'ref-section-field': 'Referenced section'
            });
        });

        it('groups the affected fields per kind', () => {
            component.typeInstance = buildType({
                fields: [
                    { name: 'hostname', label: 'Hostname', type: 'text' },
                    { name: 'owner', label: 'Owner', type: 'ref' },
                    { name: 'rack', label: 'Rack', type: 'ref' },
                    { name: 'site', label: 'Site', type: 'location' }
                ]
            });

            component.initMapping();

            expect(component.unsupportedFieldGroups).toEqual([
                { kind: 'Reference', names: 'Owner, Rack' },
                { kind: 'Location', names: 'Site' }
            ]);
        });

        it('falls back to the technical name when a field has no label', () => {
            component.typeInstance = buildType({ fields: [{ name: 'owner_id', label: '', type: 'ref' }] });

            component.initMapping();

            expect(component.unsupportedFieldGroups).toEqual([{ kind: 'Reference', names: 'owner_id' }]);
        });

        it('warns about referenced sections as their own kind', () => {
            component.typeInstance = buildType({
                fields: [{ name: 'linked', label: 'Linked section', type: 'ref-section-field' }]
            });

            component.initMapping();

            expect(component.unsupportedFieldGroups).toEqual([{ kind: 'Referenced section', names: 'Linked section' }]);
        });

        it('warns about nothing for a type without unsupported fields', () => {
            component.typeInstance = buildType({ fields: [{ name: 'hostname', label: 'Hostname', type: 'text' }] });

            component.initMapping();

            expect(component.unsupportedFieldGroups).toEqual([]);
        });

        it('warns about nothing for a type without any field', () => {
            component.typeInstance = buildType({ fields: [] });

            component.initMapping();

            expect(component.unsupportedFieldGroups).toEqual([]);
            expect(component.mappingControls.map((control: any) => control.name)).toEqual(['public_id', 'active']);
        });

        it('cannot build the mapping for a type that carries no field list at all', () => {
            // Known gap: `initMapping` iterates `typeInstance.fields` unguarded while the warning
            // helper next to it defends with `?? []`. Delete this test once the loop is guarded too.
            component.typeInstance = buildType({ fields: undefined });

            expect(() => component.initMapping()).toThrow();
        });

        it('clears the previous warning when another type is chosen', () => {
            component.typeInstance = buildType({ fields: [{ name: 'owner', label: 'Owner', type: 'ref' }] });
            component.initMapping();

            component.typeInstance = buildType({ fields: [{ name: 'hostname', label: 'Hostname', type: 'text' }] });
            component.initMapping();

            expect(component.unsupportedFieldGroups).toEqual([]);
        });
    });

    describe('re-parsed file', () => {
        beforeEach(() => {
            component.ngOnInit();
            component.typeInstance = buildType();
        });

        it('rebuilds the mapping when the file was parsed again', () => {
            component.parsedData = { header: ['hostname'], entry_length: 1 };

            component.ngOnChanges(parsedDataChange(component.parsedData));

            expect(component.mappingContainer.createComponent).toHaveBeenCalled();
        });

        it('ignores the initial binding of the parsed file', () => {
            component.ngOnChanges(parsedDataChange({ header: [], entry_length: 0 }, true));

            expect(component.mappingContainer.createComponent).not.toHaveBeenCalled();
        });

        it('ignores a parse result that was reset to undefined', () => {
            component.ngOnChanges(parsedDataChange(undefined));

            expect(component.mappingContainer.createComponent).not.toHaveBeenCalled();
        });
    });

    describe('leaving the step', () => {
        it('releases the type list, value change and type id subscriptions', () => {
            component.ngOnInit();

            component.ngOnDestroy();
            component.configForm.get('typeID').patchValue(99);

            expect(typeService.getType).not.toHaveBeenCalledWith(99);
        });
    });
});
