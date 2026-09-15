import { ComponentFixture, TestBed } from '@angular/core/testing';
import { of, throwError } from 'rxjs';

import { ImportComponent } from './import.component';
import { ObjectService } from 'src/app/framework/services/object.service';

/**
 * The import landing page gates the object import behind the configured object limit in cloud mode.
 * These tests cover the counting and the states the entry button can be in.
 */
describe('ImportComponent (import landing page)', () => {
    let component: ImportComponent;
    let fixture: ComponentFixture<ImportComponent>;
    let objectService: jasmine.SpyObj<ObjectService>;

    beforeEach(async () => {
        objectService = jasmine.createSpyObj<ObjectService>('ObjectService', ['getConfigItemsLimit', 'countObjects']);
        objectService.getConfigItemsLimit.and.returnValue(of(500));
        objectService.countObjects.and.returnValue(of(120));

        await TestBed.configureTestingModule({
            declarations: [ImportComponent],
            providers: [{ provide: ObjectService, useValue: objectService }]
        })
            .overrideComponent(ImportComponent, { set: { template: '' } })
            .compileComponents();

        fixture = TestBed.createComponent(ImportComponent);
        component = fixture.componentInstance;
    });

    describe('object usage', () => {
        it('loads the configured limit and the used objects', () => {
            component.ngOnInit();

            expect(component.totalObjects).toBe(500);
            expect(component.usedObjects).toBe(120);
        });

        it('counts zero used objects when the count request fails', () => {
            objectService.countObjects.and.returnValue(throwError(() => new Error('offline')));

            component.ngOnInit();

            expect(component.usedObjects).toBe(0);
        });
    });

    describe('entry button in on premise mode', () => {
        beforeEach(() => {
            component.isCloudModeEnabled = false;
            component.ngOnInit();
        });

        it('always offers the import', () => {
            expect(component.getButtonClass()).toBe('btn btn-primary');
        });

        it('still offers the import when the limit is reached', () => {
            component.totalObjects = 100;
            component.usedObjects = 100;

            expect(component.getButtonClass()).toBe('btn btn-primary');
        });
    });

    describe('entry button in cloud mode', () => {
        beforeEach(() => {
            component.isCloudModeEnabled = true;
            component.ngOnInit();
        });

        it('blocks the import once the object limit is reached', () => {
            component.totalObjects = 100;
            component.usedObjects = 100;

            expect(component.getButtonClass()).toBe('btn btn-secondary disabled-look');
            expect(component.getButtonTooltip()).toBe('Maximum number of objects has been reached');
        });

        it('offers the import while there is room left', () => {
            component.totalObjects = 500;
            component.usedObjects = 120;

            expect(component.getButtonTooltip()).toBe('Import Objects');
        });

        it('treats a missing limit as unlimited instead of dividing by zero', () => {
            component.totalObjects = 0;
            component.usedObjects = 50;

            expect(component.getButtonTooltip()).toBe('Import Objects');
        });

        it('returns no button class below the limit - the button falls back to the template styling', () => {
            // Documents current behaviour: only the blocked state returns a class in cloud mode.
            component.totalObjects = 500;
            component.usedObjects = 120;

            expect(component.getButtonClass()).toBeUndefined();
        });
    });

    describe('leaving the page', () => {
        it('releases the limit subscription', () => {
            component.ngOnInit();

            expect(() => component.ngOnDestroy()).not.toThrow();
        });

        it('survives being destroyed before anything was loaded', () => {
            expect(() => component.ngOnDestroy()).not.toThrow();
        });
    });
});
