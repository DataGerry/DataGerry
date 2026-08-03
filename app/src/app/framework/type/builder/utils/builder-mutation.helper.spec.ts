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
import { CmdbMode } from '../../../modes.enum';
import { BuilderContext } from './builder-context';
import { BuilderInteractionPolicy } from './builder-interaction-policy';
import { BuilderMutationHelper } from './builder-mutation.helper';

/**
 * Direct unit tests for the builder's model-mutation logic. Collaborators (policy/highlight/template)
 * and services are stubbed so each behaviour is verified in isolation against a live BuilderContext.
 */
describe('BuilderMutationHelper', () => {
    let ctx: BuilderContext;
    let deps: any;
    let policy: BuilderInteractionPolicy;
    let highlight: any;
    let templateManager: any;
    let helper: BuilderMutationHelper;

    // Named handles into the fixture graph so tests can act on specific sections/fields.
    let sectionA: any;
    let sectionB: any;
    let fieldA: any;
    let fieldB: any;

    function build(): void {
        fieldA = { name: 'field_a', type: 'text', label: 'Field A' };
        fieldB = { name: 'field_b', type: 'text', label: 'Field B' };
        sectionA = { name: 'section_a', label: 'A', type: 'section', fields: [fieldA] };
        sectionB = { name: 'section_b', label: 'B', type: 'section', fields: [fieldB] };

        const typeInstance: any = {
            fields: [fieldA, fieldB],
            render_meta: { sections: [sectionA, sectionB], externals: [] },
            global_template_ids: []
        };

        ctx = {
            sections: [sectionA, sectionB],
            typeInstance,
            newSections: [],
            newFields: [],
            globalSectionTemplates: [],
            selectedGlobalSectionTemplates: [],
            lockedSectionNames: [],
            lockedFieldNames: [],
            disableFields: false,
            mode: CmdbMode.Create,
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

        deps = {
            validationService: jasmine.createSpyObj('ValidationService',
                ['setSectionValid', 'updateFieldValidityOnDeletion', 'setDisableFields',
                 'setSectionWithoutFieldState', 'setSectionHighlightState', 'setFieldHighlightState',
                 'updateSectionKey', 'setIsValid']),
            sectionIdentifierService: jasmine.createSpyObj('SectionIdentifierService',
                ['removeSection', 'syncSections', 'getDroppedIndex', 'addSection', 'setActiveIndex']),
            fieldIdentifierValidation: jasmine.createSpyObj('FieldIdentifierValidationService',
                ['clearFieldNames', 'addFieldNames']),
            locationFieldDeletion: jasmine.createSpyObj('LocationFieldDeletionService',
                ['sectionContainsLocationField', 'canDelete', 'isLocationField']),
            renderer: jasmine.createSpyObj('Renderer2', ['setStyle']),
            el: { nativeElement: { querySelector: () => null } }
        };

        policy = new BuilderInteractionPolicy(() => ({
            selectedGlobalSectionTemplates: ctx.selectedGlobalSectionTemplates,
            globalTemplateIds: ctx.typeInstance?.global_template_ids ?? [],
            globalFieldNames: [],
            schemaLockedSectionNames: ctx.lockedSectionNames,
            schemaLockedFieldNames: ctx.lockedFieldNames
        }));

        highlight = jasmine.createSpyObj('BuilderHighlightHelper',
            ['updateHighlightState', 'updateSectionFieldStatus', 'isAnySectionHighlighted']);
        templateManager = jasmine.createSpyObj('BuilderTemplateManager',
            ['handleGlobalTemplates', 'extractSectionData', 'setSectionTemplateFields']);

        helper = new BuilderMutationHelper(ctx, deps, policy, highlight, templateManager);
    }

    beforeEach(build);

    describe('duplicate-identifier lock release', () => {

        it('releases the lock when the conflicting section is removed and no duplicate remains', () => {
            ctx.disableFields = true;
            ctx.activeDuplicateField = { sectionIndex: 1, fieldIndex: 0 };

            helper.removeSection(sectionA, 0);

            expect(ctx.disableFields).toBe(false);
            expect(ctx.activeDuplicateField).toBeNull();
            expect(deps.validationService.setDisableFields).toHaveBeenCalledWith(false);
        });

        it('keeps the lock when a duplicate identifier still remains after removal', () => {
            // section_b and section_c share a name; removing the unrelated section_a must NOT unlock.
            const sectionC = { name: 'section_b', label: 'C', type: 'section', fields: [{ name: 'field_c', type: 'text' }] };
            ctx.sections.push(sectionC);
            ctx.typeInstance.render_meta.sections.push(sectionC);
            ctx.typeInstance.fields.push(sectionC.fields[0]);
            ctx.disableFields = true;

            helper.removeSection(sectionA, 0);

            expect(ctx.disableFields).toBe(true);
        });

        it('releases the lock when a duplicate field is removed', () => {
            // Both fields share an identifier -> a real field duplicate.
            fieldA.name = 'dupe';
            fieldB.name = 'dupe';
            ctx.disableFields = true;

            helper.removeField(fieldB, sectionB);

            expect(ctx.disableFields).toBe(false);
        });

        it('commits a duplicate section identifier and preserves it after the conflict is removed', () => {
            // Mirrors the section editor: commit the typed name first, then raise the duplicate flag.
            helper.onFieldChange({ newValue: 'section_a', inputName: 'name', previousName: 'section_b', elementType: 'section' });
            helper.onFieldChange({ isDuplicate: true, elementType: 'section' });

            expect(ctx.disableFields).toBe(true);
            expect(ctx.sections[1].name).toBe('section_a');
            expect(ctx.typeInstance.render_meta.sections[1].name).toBe('section_a');

            helper.removeSection(sectionA, 0);

            expect(ctx.disableFields).toBe(false);
            expect(ctx.typeInstance.render_meta.sections.length).toBe(1);
            expect(ctx.typeInstance.render_meta.sections[0].name).toBe('section_a');
        });
    });

    describe('section removal preserves the surviving section (identifier-clearing bug)', () => {

        it('keeps the remaining section identifier intact when another section is removed', () => {
            helper.removeSection(sectionA, 0);

            expect(ctx.typeInstance.render_meta.sections.length).toBe(1);
            expect(ctx.typeInstance.render_meta.sections[0].name).toBe('section_b');
            expect(ctx.sections.length).toBe(1);
            expect(ctx.sections[0].name).toBe('section_b');
        });

        it('keeps the surviving field identifiers intact after removing a section', () => {
            helper.removeSection(sectionA, 0);

            expect(ctx.typeInstance.fields.map((f: any) => f.name)).toEqual(['field_b']);
        });
    });

    describe('location field cannot enter a multi-data-section', () => {

        function dropEvent(field: any) {
            return { data: field, dropEffect: 'copy', index: 0, event: { preventDefault: () => {} } } as any;
        }

        it('rejects a location field dropped into a multi-data-section', () => {
            const multi = { name: 'md', label: 'MD', type: 'multi-data-section', fields: [] };
            ctx.sections = [multi];
            ctx.typeInstance.render_meta.sections = [multi];
            ctx.typeInstance.fields = [];

            helper.onFieldDrop(dropEvent({ name: 'dg_location', type: 'location' }), multi);

            expect(multi.fields.length).toBe(0);
            expect(ctx.typeInstance.fields.some((f: any) => f.type === 'location')).toBe(false);
        });

        it('allows a location field into a normal section', () => {
            const normal = { name: 'normal', label: 'N', type: 'section', fields: [] };
            ctx.sections = [normal];
            ctx.typeInstance.render_meta.sections = [normal];
            ctx.typeInstance.fields = [];

            helper.onFieldDrop(dropEvent({ name: 'dg_location', type: 'location' }), normal);

            expect(normal.fields.length).toBe(1);
            expect(ctx.typeInstance.fields.some((f: any) => f.type === 'location')).toBe(true);
        });

        it('allows a regular field into a multi-data-section', () => {
            const multi = { name: 'md', label: 'MD', type: 'multi-data-section', fields: [] };
            ctx.sections = [multi];
            ctx.typeInstance.render_meta.sections = [multi];
            ctx.typeInstance.fields = [];

            helper.onFieldDrop(dropEvent({ name: 'a_text', type: 'text' }), multi);

            expect(multi.fields.length).toBe(1);
        });
    });
});
