/*
* DATAGERRY - OpenSource Enterprise CMDB
* Copyright (C) 2026 becon GmbH
*
* This program is free software: you can redistribute it and/or modify
* it under the terms of the GNU Affero General Public License as
* published by the Free Software Foundation, either version 3 of the
* License, or (at your option) any later version.
*
* This program is distributed in the hope that it will be useful,
* but WITHOUT ANY WARRANTY; without even the implied warranty of
* MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
* GNU Affero General Public License for more details.
*
* You should have received a copy of the GNU Affero General Public License
* along with this program. If not, see <https://www.gnu.org/licenses/>.
*/
import { TestBed, fakeAsync, flush, tick } from '@angular/core/testing';
import { NO_ERRORS_SCHEMA } from '@angular/core';
import { ReactiveFormsModule } from '@angular/forms';

import { Subject } from 'rxjs';

import { CmdbMode } from '../../modes.enum';
import { CmdbTypeSchemaAdapter } from '../schema/cmdb-type-schema.adapter';
import { SectionFieldEditComponent } from '../configs/section/section-field-edit.component';
import { ValidationService } from '../services/validation.service';
import { SectionIdentifierService } from '../services/SectionIdentifierService.service';
import { CopyService } from '../../../core/services/copy.service';
import { BuilderContext } from './builder-context';
import { BuilderInteractionPolicy, BuilderInteractionPolicyContext } from './builder-interaction-policy';
import { BuilderHighlightHelper } from './builder-highlight.helper';
import { BuilderTemplateManager } from './builder-template.manager';
import { BuilderMutationHelper } from './builder-mutation.helper';
/* ------------------------------------------------------------------------------------------------------------------ */

/**
 * A duplicate identifier latches `disableFields`, which locks every other config form in the builder
 * and disables Next and Save until it is resolved. Getting *into* that state is easy; the failure
 * mode that matters is never getting back out - a builder stuck with everything greyed out and no
 * way to save. Every route out of the latch is covered here: renaming, removing the offending field,
 * and removing the whole section.
 */
describe('Builder duplicate identifiers', () => {

    interface Harness {
        ctx: BuilderContext & { typeInstance: any };
        highlight: BuilderHighlightHelper;
        mutation: BuilderMutationHelper;
        deps: any;
        validationService: any;
    }

    function harness(seed: any = {}): Harness {
        const sections = seed.sections ?? [];
        const typeInstance: any = seed.typeInstance ?? {
            fields: sections.flatMap((s: any) => s.fields ?? []).filter((f: any) => typeof f === 'object'),
            render_meta: { sections: [...sections], externals: [] },
            global_template_ids: []
        };

        const ctx: BuilderContext & { typeInstance: any } = {
            sections,
            schema: new CmdbTypeSchemaAdapter(typeInstance),
            typeInstance,
            newSections: [],
            newFields: [],
            globalSectionTemplates: [],
            selectedGlobalSectionTemplates: [],
            lockedSectionNames: [],
            lockedFieldNames: [],
            disableFields: false,
            mode: seed.mode ?? CmdbMode.Create,
            activeIndex: null,
            draggedSectionIndex: null,
            pendingSectionDropIndex: null,
            draggedField: null,
            activeDuplicateField: null,
            prevSectionHighlighted: false,
            prevFieldHighlighted: false,
            sectionReference: null,
            initialFieldNames: null,
            initialIdentifier: ''
        };

        const validationService = jasmine.createSpyObj('ValidationService',
            ['setSectionValid', 'updateFieldValidityOnDeletion', 'setDisableFields', 'setSectionWithoutFieldState',
                'setSectionHighlightState', 'setFieldHighlightState', 'updateSectionKey', 'setIsValid']);

        const deps = {
            validationService,
            sectionIdentifierService: jasmine.createSpyObj('SectionIdentifierService',
                ['removeSection', 'syncSections', 'getDroppedIndex', 'addSection', 'setActiveIndex']),
            fieldIdentifierValidation: jasmine.createSpyObj('FieldIdentifierValidationService',
                ['clearFieldNames', 'addFieldNames']),
            deletionGuard: jasmine.createSpyObj('BuilderDeletionGuard',
                ['sectionContainsLocationField', 'canDelete', 'isLocationField']),
            renderer: jasmine.createSpyObj('Renderer2', ['setStyle']),
            el: { nativeElement: { querySelector: () => null } }
        };

        const policyContext = (): BuilderInteractionPolicyContext => ({
            selectedGlobalSectionTemplates: [],
            globalTemplateIds: ctx.schema.readGlobalTemplateIds(),
            globalFieldNames: [],
            schemaLockedSectionNames: [],
            schemaLockedFieldNames: []
        });

        const policy = new BuilderInteractionPolicy(policyContext);
        const highlight = new BuilderHighlightHelper(ctx, policy, validationService);
        const templateManager = new BuilderTemplateManager(ctx, policy);
        const mutation = new BuilderMutationHelper(ctx, deps, policy, highlight, templateManager);

        return { ctx, highlight, mutation, deps, validationService };
    }

    function section(name: string, extra: any = {}): any {
        return { name, label: extra.label ?? name.toUpperCase(), type: extra.type ?? 'section', fields: extra.fields ?? [], ...extra };
    }

    function field(name: string, extra: any = {}): any {
        return { name, label: extra.label ?? name.toUpperCase(), type: extra.type ?? 'text', ...extra };
    }

    /** The event a config editor emits when its identifier collides with another one. */
    function duplicateReport(isDuplicate: boolean, elementType = 'section'): any {
        return { isDuplicate, elementType };
    }

    /* ================================================================================================================ */
    /*                                                CLOSING THE LATCH                                                 */
    /* ================================================================================================================ */

    describe('closing the latch', () => {

        it('locks the builder and remembers which editor holds the duplicate', () => {
            const h = harness({ sections: [section('s', { fields: [field('a'), field('b')] })] });

            h.mutation.onFieldChange(duplicateReport(true), 0, 1);

            expect(h.ctx.disableFields).toBeTrue();
            expect(h.ctx.activeDuplicateField).toEqual({ sectionIndex: 0, fieldIndex: 1 });
            expect(h.validationService.setDisableFields).toHaveBeenCalledWith(true);
        });


        it('does not apply the report as a field value change', () => {
            const target = field('a');
            const h = harness({ sections: [section('s', { fields: [target] })] });

            h.mutation.onFieldChange(duplicateReport(true), 0, 0);

            expect(target).toEqual(field('a'));
        });


        /** The wizard binds Save to this flag, so a redundant push would churn the button every tick. */
        it('notifies the wizard only when the flag actually flips', () => {
            const h = harness({ sections: [section('s', { fields: [field('a')] })] });

            h.mutation.onFieldChange(duplicateReport(true), 0, 0);
            h.mutation.onFieldChange(duplicateReport(true), 0, 0);

            expect(h.validationService.setDisableFields).toHaveBeenCalledTimes(1);
        });
    });

    /* ================================================================================================================ */
    /*                                              RELEASING THE LATCH                                                 */
    /* ================================================================================================================ */

    describe('releasing the latch', () => {

        it('releases when the editor reports the conflict resolved', () => {
            const h = harness({ sections: [section('s', { fields: [field('a')] })] });
            h.mutation.onFieldChange(duplicateReport(true), 0, 0);

            h.mutation.onFieldChange(duplicateReport(false), 0, 0);

            expect(h.ctx.disableFields).toBeFalse();
            expect(h.ctx.activeDuplicateField).toBeNull();
            expect(h.validationService.setDisableFields).toHaveBeenCalledWith(false);
        });


        /**
         * The rename path. Renaming the offending identifier emits an ordinary value change, not a
         * duplicate report - so an ordinary change has to clear the latch too, or the builder stays
         * locked with a name that is already unique.
         */
        it('releases when the offending identifier is renamed', () => {
            const target = field('dup');
            const h = harness({ sections: [section('s', { fields: [target] })] });
            h.mutation.onFieldChange(duplicateReport(true), 0, 0);

            h.mutation.onFieldChange({
                newValue: 'unique', inputName: 'name', fieldName: 'dup', previousName: 'dup', elementType: 'text'
            });

            expect(h.ctx.disableFields).toBeFalse();
            expect(h.ctx.activeDuplicateField).toBeNull();
            expect(target.name).toBe('unique');
        });


        /**
         * Removing the conflicting field never routes through the editor's duplicate report, so the
         * latch has to be re-evaluated against the whole model after any removal - otherwise deleting
         * the duplicate leaves the builder permanently locked.
         */
        it('releases when the duplicate field is removed instead of renamed', () => {
            const keeper = field('dup');
            const offender = field('dup');
            const s = section('s', { fields: [keeper, offender] });
            const h = harness({ sections: [s] });
            h.mutation.onFieldChange(duplicateReport(true), 0, 1);

            h.mutation.removeField(offender, s);

            expect(h.ctx.disableFields).toBeFalse();
            expect(h.ctx.activeDuplicateField).toBeNull();
        });


        it('releases when the whole offending section is removed', () => {
            const first = section('dup', { fields: [field('a')] });
            const second = section('dup', { fields: [field('b')] });
            const h = harness({ sections: [first, second] });
            h.mutation.onFieldChange(duplicateReport(true), 1, 0);

            h.mutation.removeSection(second, 1);

            expect(h.ctx.disableFields).toBeFalse();
        });


        it('keeps the latch closed while a second duplicate is still unresolved', () => {
            const s = section('s', {
                fields: [field('dup'), field('dup'), field('other'), field('other')]
            });
            const h = harness({ sections: [s] });
            h.mutation.onFieldChange(duplicateReport(true), 0, 1);

            h.mutation.removeField(s.fields[1], s);

            expect(h.ctx.disableFields).withContext('"other" is still duplicated').toBeTrue();
        });


        it('sees a duplicate among section identifiers, not only field ones', () => {
            const first = section('dup', { fields: [field('a')] });
            const second = section('dup', { fields: [field('b')] });
            const third = section('third', { fields: [field('c')] });
            const h = harness({ sections: [first, second, third] });
            h.mutation.onFieldChange(duplicateReport(true), 1, 0);

            h.mutation.removeField(third.fields[0], third);

            expect(h.ctx.disableFields).withContext('two sections still share "dup"').toBeTrue();
        });


        it('does not release a latch that was never closed', () => {
            const s = section('s', { fields: [field('a')] });
            const h = harness({ sections: [s] });

            h.mutation.removeField(s.fields[0], s);

            expect(h.validationService.setDisableFields).not.toHaveBeenCalled();
        });
    });

    /* ================================================================================================================ */
    /*                                          A DUPLICATE IS ALSO HIGHLIGHTED                                         */
    /* ================================================================================================================ */

    describe('highlighting a duplicate', () => {

        it('flags both fields sharing an identifier, and their section', () => {
            const first = field('dup');
            const second = field('dup');
            const s = section('s', { fields: [first, second] });
            const h = harness({ sections: [s] });

            expect(h.highlight.isFieldHighlighted(first)).toBeTrue();
            expect(h.highlight.isFieldHighlighted(second)).toBeTrue();
            expect(h.highlight.isSectionHighlighted(s)).toBeTrue();
        });


        it('flags both sections sharing an identifier', () => {
            const first = section('dup', { fields: [field('a')] });
            const second = section('dup', { fields: [field('b')] });
            const h = harness({ sections: [first, second] });

            expect(h.highlight.isSectionHighlighted(first)).toBeTrue();
            expect(h.highlight.isSectionHighlighted(second)).toBeTrue();
        });


        it('stops flagging once the identifier is made unique again', () => {
            const first = field('dup');
            const second = field('dup');
            const s = section('s', { fields: [first, second] });
            const h = harness({ sections: [s] });

            second.name = 'unique';

            expect(h.highlight.isFieldHighlighted(first)).toBeFalse();
            expect(h.highlight.isFieldHighlighted(second)).toBeFalse();
            expect(h.highlight.isSectionHighlighted(s)).toBeFalse();
        });
    });
});


/* ==================================================================================================================== */
/*                             THE EDITOR THAT DETECTS THE DUPLICATE IN THE FIRST PLACE                                 */
/* ==================================================================================================================== */

/**
 * `SectionFieldEditComponent` serves both `section` and `multi-data-section`, and the two branch on
 * the section's own type in one spot: a multi-data-section reports the duplicate and **stops**, while
 * a plain section reports the value change first and flags the duplicate after. That divergence is
 * inherited from the two editors this component was merged from and is preserved deliberately -
 * reconciling it changes MDS behaviour and is a product decision.
 */
describe('SectionFieldEditComponent duplicate detection', () => {

    let component: SectionFieldEditComponent;
    let activeIndexSubject: Subject<number | null>;

    beforeEach(async () => {
        activeIndexSubject = new Subject<number | null>();

        await TestBed.configureTestingModule({
            declarations: [SectionFieldEditComponent],
            imports: [ReactiveFormsModule],
            providers: [
                {
                    provide: ValidationService,
                    useValue: jasmine.createSpyObj('ValidationService',
                        ['setIsValid', 'updateFieldValidityOnDeletion', 'setSectionHighlightState'])
                },
                {
                    provide: SectionIdentifierService,
                    useValue: jasmine.createSpyObj('SectionIdentifierService', {
                        getActiveIndex: activeIndexSubject.asObservable(),
                        updateSection: true
                    })
                },
                { provide: CopyService, useValue: jasmine.createSpyObj('CopyService', ['copyWithFeedback']) }
            ],
            schemas: [NO_ERRORS_SCHEMA]
        }).compileComponents();

        const fixture = TestBed.createComponent(SectionFieldEditComponent);
        component = fixture.componentInstance;
        fixture.detectChanges();
    });

    /** Collects everything the editor emits for one input change. */
    function emissionsFor(value: string, type: string): Array<any> {
        const events: Array<any> = [];
        component.fieldChanges$.subscribe(event => events.push(event));
        component.nameControl.setValue(value, { emitEvent: false });
        component.onInputChange(value, type);
        return events;
    }

    it('does not treat the section\'s own identifier as a duplicate', fakeAsync(() => {
        component.data = { name: 'mine', label: 'Mine', type: 'section' };
        component.sections = [{ name: 'other', type: 'section' }, component.data];

        const events = emissionsFor('mine', 'name');
        tick(300);
        flush();

        expect(events.find(event => 'isDuplicate' in event).isDuplicate).toBeFalse();
        expect(component.isIdentifierValid).toBeTrue();
    }));


    it('reports a collision with another section', fakeAsync(() => {
        component.data = { name: 'mine', label: 'Mine', type: 'section' };
        component.sections = [{ name: 'taken', type: 'section' }, component.data];

        const events = emissionsFor('taken', 'name');
        tick(300);
        flush();

        expect(events.find(event => 'isDuplicate' in event).isDuplicate).toBeTrue();
        expect(component.isIdentifierValid).toBeFalse();
        expect(component.nameControl.errors?.duplicateIdentifier).toBeTrue();
    }));


    it('clears the error once the identifier is renamed to a free one', fakeAsync(() => {
        component.data = { name: 'mine', label: 'Mine', type: 'section' };
        component.sections = [{ name: 'taken', type: 'section' }, component.data];

        emissionsFor('taken', 'name');
        tick(300);
        expect(component.nameControl.errors?.duplicateIdentifier).toBeTrue();

        const events = emissionsFor('free', 'name');
        tick(300);
        flush();

        expect(component.isIdentifierValid).toBeTrue();
        expect(component.nameControl.errors?.duplicateIdentifier).toBeUndefined();
        expect(events.find(event => 'isDuplicate' in event).isDuplicate).toBeFalse();
    }));


    it('never reports an empty identifier as a duplicate', fakeAsync(() => {
        component.data = { name: 'mine', label: 'Mine', type: 'section' };
        component.sections = [{ name: '', type: 'section' }, component.data];

        const events = emissionsFor('', 'name');
        tick(300);
        flush();

        expect(events.find(event => 'isDuplicate' in event).isDuplicate).toBeFalse();
    }));


    it('leaves a label change alone - only identifiers collide', fakeAsync(() => {
        component.data = { name: 'mine', label: 'Mine', type: 'section' };
        component.sections = [{ name: 'taken', type: 'section' }, component.data];

        const events = emissionsFor('taken', 'label');
        tick(300);
        flush();

        expect(events.some(event => 'isDuplicate' in event)).toBeFalse();
        expect(component.isIdentifierValid).toBeTrue();
    }));


    /* --------------------------------------- THE DELIBERATE MDS DIVERGENCE --------------------------------------- */

    it('still reports the value change for a plain section holding a duplicate', fakeAsync(() => {
        component.data = { name: 'mine', label: 'Mine', type: 'section' };
        component.sections = [{ name: 'taken', type: 'section' }, component.data];

        const events = emissionsFor('taken', 'name');
        tick(300);
        flush();

        const valueChange = events.find(event => event.inputName === 'name');
        expect(valueChange).withContext('a section commits the value, then flags it').toBeTruthy();
        expect(valueChange.newValue).toBe('taken');
        expect(valueChange.elementType).toBe('section');
    }));


    it('stops at the report for a multi-data-section holding a duplicate', fakeAsync(() => {
        component.data = { name: 'mine', label: 'Mine', type: 'multi-data-section' };
        component.sections = [{ name: 'taken', type: 'multi-data-section' }, component.data];

        const events = emissionsFor('taken', 'name');
        tick(300);
        flush();

        expect(events.length).withContext('the MDS branch returns straight after the report').toBe(1);
        expect(events[0]).toEqual({ isDuplicate: true, elementType: 'multi-data-section' });
    }));


    it('commits the value for a multi-data-section once the identifier is free', fakeAsync(() => {
        component.data = { name: 'mine', label: 'Mine', type: 'multi-data-section' };
        component.sections = [{ name: 'taken', type: 'multi-data-section' }, component.data];

        const events = emissionsFor('free', 'name');
        tick(300);
        flush();

        expect(events.find(event => event.inputName === 'name').elementType).toBe('multi-data-section');
        expect(events.filter(event => 'isDuplicate' in event).map(event => event.isDuplicate)).toEqual([false]);
    }));
});
