import { ComponentFixture, TestBed, fakeAsync, tick, flush } from '@angular/core/testing';
import { NO_ERRORS_SCHEMA } from '@angular/core';
import { ReactiveFormsModule, UntypedFormControl, Validators } from '@angular/forms';
import { SectionFieldEditComponent } from './section-field-edit.component';

import { ReplaySubject, of, Subject } from 'rxjs';
import { SectionIdentifierService } from 'src/app/framework/builder/services/SectionIdentifierService.service';
import { ValidationService } from 'src/app/framework/builder/services/validation.service';

describe('SectionFieldEditComponent', () => {
    let component: SectionFieldEditComponent;
    let fixture: ComponentFixture<SectionFieldEditComponent>;
    let validationService: jasmine.SpyObj<ValidationService>;
    let sectionIdentifier: jasmine.SpyObj<SectionIdentifierService>;
    let activeIndexSubject: Subject<number | null>;


    beforeEach(async () => {
        const validationServiceSpy = jasmine.createSpyObj('ValidationService', ['setIsValid', 'updateFieldValidityOnDeletion', 'setSectionHighlightState']);
        activeIndexSubject = new Subject<number | null>();
        const sectionIdentifierSpy = jasmine.createSpyObj('SectionIdentifierService', {
            getActiveIndex: activeIndexSubject.asObservable(),
            updateSection: true,
        });

        await TestBed.configureTestingModule({
            declarations: [SectionFieldEditComponent],
            imports: [ReactiveFormsModule],
            providers: [
                { provide: ValidationService, useValue: validationServiceSpy },
                { provide: SectionIdentifierService, useValue: sectionIdentifierSpy }
            ],
            schemas: [NO_ERRORS_SCHEMA]
        }).compileComponents();

        fixture = TestBed.createComponent(SectionFieldEditComponent);
        component = fixture.componentInstance;
        validationService = TestBed.inject(ValidationService) as jasmine.SpyObj<ValidationService>;
        sectionIdentifier = TestBed.inject(SectionIdentifierService) as jasmine.SpyObj<SectionIdentifierService>;
        fixture.detectChanges();
    });


    it('should create the component', () => {
        expect(component).toBeTruthy();
    });


    it('should update initialValue when onInputChange is called with name type', fakeAsync(() => {
        const newValue = 'Updated Name';
        component.nameControl.setValue(newValue);
        component.onInputChange(newValue, 'name');
        tick();
        flush();

        expect(component.nameControl.value).toBe(newValue);
    }));


    it('should update isValid$ when form controls are updated', fakeAsync(() => {
        component.ngOnInit();

        // Initially, form is invalid because fields are empty
        expect(component.isValid$).toBeFalse();

        // Set values to make the form valid
        component.nameControl.setValue('Valid Name');
        component.labelControl.setValue('Valid Label');
        tick();

        expect(component.isValid$).toBeTrue();

        // Ensure any remaining timers are flushed at the end
        flush();
    }));


    it('commits a duplicate identifier to the model instead of dropping it', fakeAsync(() => {
        component.data = { name: 'me', label: 'Me', type: 'section' };
        component.sections = [{ name: 'taken', type: 'section' }, component.data];
        (component as any).currentValue = 'me';
        (component as any).initialValue = 'me';
        // The real identifier service rejects a duplicate (returns false); reflect that here.
        sectionIdentifier.updateSection.and.returnValue(false);

        const events: any[] = [];
        component.fieldChanges$.subscribe(event => events.push(event));

        component.nameControl.setValue('taken', { emitEvent: false });
        component.onInputChange('taken', 'name');
        tick(300);
        flush();

        const nameCommit = events.find(event => event.inputName === 'name' && event.newValue === 'taken');
        const duplicateFlag = events.find(event => event.isDuplicate === true);

        expect(nameCommit)
            .withContext('the typed identifier must still be committed to the model even when duplicate')
            .toBeTruthy();
        expect(duplicateFlag)
            .withContext('the duplicate must still be flagged so the builder locks')
            .toBeTruthy();
        expect(component.isIdentifierValid).toBeFalse();
    }));

    /* ------------------------------ SECTION FLAVOUR + IDENTIFIER SYNC ------------------------------ */

    describe('section flavour', () => {

        it('emits elementType "section" for a plain section', fakeAsync(() => {
            component.data = { type: 'section', name: 'sec', label: 'Section' };
            const events: any[] = [];
            component.fieldChanges$.subscribe(event => events.push(event));

            component.onInputChange('renamed', 'label');
            tick(300);
            flush();

            expect(events.every(event => event.elementType === 'section')).toBeTrue();
        }));


        it('emits elementType "multi-data-section" for a multi-data section', fakeAsync(() => {
            component.data = { type: 'multi-data-section', name: 'mds', label: 'MDS' };
            const events: any[] = [];
            component.fieldChanges$.subscribe(event => events.push(event));

            component.onInputChange('renamed', 'label');
            tick(300);
            flush();

            expect(events.every(event => event.elementType === 'multi-data-section')).toBeTrue();
        }));
    });


    describe('identifier sync', () => {

        it('skips the identifier registry when no section is active, without flagging a conflict', fakeAsync(() => {
            // The section template builder owns a single fixed section and never registers it, so
            // its active index stays null. Asking the registry to rename anyway used to report a
            // false "identifier must be unique" on that page as soon as the section was an MDS.
            component.data = { type: 'multi-data-section', name: 'dg_gst-1', label: 'Template' };

            // Must move the control, otherwise updateSectionValue short-circuits on
            // `newValue === currentValue` and the test would pass without reaching the guard.
            component.nameControl.setValue('dg_gst-2', { emitEvent: false });
            component.onInputChange('dg_gst-2', 'name');
            tick(300);
            flush();

            expect(sectionIdentifier.updateSection).not.toHaveBeenCalled();
            expect(component.isIdentifierValid)
                .withContext('a section that was never registered must not be reported as a conflict')
                .toBeTrue();
        }));


        it('still syncs the identifier registry once a section is active', fakeAsync(() => {
            component.data = { type: 'multi-data-section', name: 'mds', label: 'MDS' };

            // updateSectionValue reads the control, not the argument, so the control has to move.
            component.nameControl.setValue('mds-renamed', { emitEvent: false });
            component.onInputChange('mds-renamed', 'name');
            activeIndexSubject.next(0);
            tick(300);
            flush();

            expect(sectionIdentifier.updateSection).toHaveBeenCalledWith(0, 'mds-renamed');
        }));
    });
});
