import { ComponentFixture, TestBed } from '@angular/core/testing';

import { ImportConfigComponent } from './import-config.component';

/**
 * The importer config step feeds start element, element limit and the overwrite flag into the request.
 * The wizard host relies on the initial values being pushed even if the user never touches the form.
 */
describe('ImportConfigComponent (object import - importer config step)', () => {
    let component: ImportConfigComponent;
    let fixture: ComponentFixture<ImportConfigComponent>;
    let emitted: unknown[];

    beforeEach(async () => {
        await TestBed.configureTestingModule({
            declarations: [ImportConfigComponent]
        })
            .overrideComponent(ImportConfigComponent, { set: { template: '' } })
            .compileComponents();

        fixture = TestBed.createComponent(ImportConfigComponent);
        component = fixture.componentInstance;

        emitted = [];
        component.configChange.subscribe((config) => emitted.push(config));
    });

    it('publishes its defaults on entering, so the host never sends an empty config', () => {
        component.ngOnInit();

        expect(emitted).toEqual([{ start_element: 0, max_elements: 0, overwrite_public: true }]);
    });

    it('publishes every change the user makes', () => {
        component.ngOnInit();

        component.configForm.get('start_element').setValue(5);
        component.configForm.get('max_elements').setValue(100);
        component.configForm.get('overwrite_public').setValue(false);

        expect(emitted.length).toBe(4);
        expect(emitted[3]).toEqual({ start_element: 5, max_elements: 100, overwrite_public: false });
    });

    it('keeps values the user typed as text, the backend receives them unparsed', () => {
        component.ngOnInit();

        component.configForm.get('max_elements').setValue('50');

        expect(emitted[1]).toEqual({ start_element: 0, max_elements: '50', overwrite_public: true });
    });

    it('stops publishing after the step was destroyed', () => {
        component.ngOnInit();
        component.ngOnDestroy();

        component.configForm.get('start_element').setValue(9);

        expect(emitted.length).toBe(1);
    });
});
