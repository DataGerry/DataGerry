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
import { CmdbMode } from '../../modes.enum';
import { CmdbTypeSchemaAdapter } from '../schema/cmdb-type-schema.adapter';
import { BuilderContext } from './builder-context';
import { BuilderInteractionPolicy, BuilderInteractionPolicyContext } from './builder-interaction-policy';
import { BuilderHighlightHelper } from './builder-highlight.helper';
import { BuilderTemplateManager } from './builder-template.manager';
import { BuilderMutationHelper } from './builder-mutation.helper';
import { BuilderUtils } from './builder-utils';

/**
 * Scenario coverage for the Type Builder, mapped to the manual regression checklist (groups A-K).
 */
describe('Type Builder scenarios (A-K)', () => {

    interface Harness {
        /** `typeInstance` is the seeded model the adapter writes through, kept for assertions. */
        ctx: BuilderContext & { typeInstance: any };
        policy: BuilderInteractionPolicy;
        highlight: BuilderHighlightHelper;
        templateManager: BuilderTemplateManager;
        mutation: BuilderMutationHelper;
        deps: any;
        validationService: any;
    }

    function buildPolicyContext(ctx: BuilderContext): BuilderInteractionPolicyContext {
        const applied = ctx.selectedGlobalSectionTemplates ?? [];
        return {
            selectedGlobalSectionTemplates: applied,
            globalTemplateIds: ctx.schema.readGlobalTemplateIds(),
            globalFieldNames: applied.flatMap(template => (template?.fields ?? []).map((field: any) => field?.name)),
            schemaLockedSectionNames: ctx.lockedSectionNames ?? [],
            schemaLockedFieldNames: ctx.lockedFieldNames ?? []
        };
    }

    function harness(seed: any = {}): Harness {
        const typeInstance: any = seed.typeInstance ?? { fields: [], render_meta: { sections: [], externals: [] }, global_template_ids: [] };

        const ctx: BuilderContext & { typeInstance: any } = {
            sections: seed.sections ?? [],
            schema: new CmdbTypeSchemaAdapter(typeInstance),
            typeInstance,
            newSections: [],
            newFields: [],
            globalSectionTemplates: seed.globalSectionTemplates ?? [],
            selectedGlobalSectionTemplates: seed.selectedGlobalSectionTemplates ?? [],
            lockedSectionNames: seed.lockedSectionNames ?? [],
            lockedFieldNames: seed.lockedFieldNames ?? [],
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

        const policy = new BuilderInteractionPolicy(() => buildPolicyContext(ctx));
        const highlight = new BuilderHighlightHelper(ctx, policy, validationService);
        const templateManager = new BuilderTemplateManager(ctx, policy);
        const mutation = new BuilderMutationHelper(ctx, deps, policy, highlight, templateManager);

        return { ctx, policy, highlight, templateManager, mutation, deps, validationService };
    }

    function section(name: string, extra: any = {}): any {
        return { name, label: extra.label ?? 'Section', type: extra.type ?? 'section', fields: extra.fields ?? [], ...extra };
    }

    function dropEvent(data: any, index = 0, dropEffect = 'copy'): any {
        return { data, index, dropEffect, event: { preventDefault: () => {} } };
    }

    /* --------------------------------------------------- A. LOAD & PALETTE -------------------------------------------- */

    describe('A. Load & palette', () => {

        it('A2: applied global templates are pulled out of the palette on load', () => {
            const applied = { name: 'net', label: 'Network', public_id: 3, fields: [{ name: 'ip', type: 'text' }] };
            const h = harness({
                globalSectionTemplates: [applied, { name: 'other', label: 'Other', public_id: 4, fields: [] }],
                typeInstance: { fields: [], render_meta: { sections: [], externals: [] }, global_template_ids: ['net'] }
            });

            h.templateManager.setSelectedGlobalTemplates();

            expect(h.ctx.selectedGlobalSectionTemplates.map((t: any) => t.name)).toContain('net');
            expect(h.ctx.globalSectionTemplates.map((t: any) => t.name)).not.toContain('net');
            expect(h.ctx.globalSectionTemplates.map((t: any) => t.name)).toContain('other');
        });

        // A1 (placeholder text/palette rendering) and A3 (groups shown only when templates exist) are
        // template-only (*ngIf) — covered by manual/e2e.
    });

    /* --------------------------------------------------- B. ADDING SECTIONS ------------------------------------------- */

    describe('B. Adding sections', () => {

        it('B1: dropping a Section structure control adds an empty section', () => {
            const h = harness();
            h.mutation.onSectionDrop(dropEvent(section('sec_1', { fields: [] })));

            expect(h.ctx.sections.length).toBe(1);
            expect(h.ctx.sections[0].type).toBe('section');
            expect(h.ctx.typeInstance.render_meta.sections[0].name).toBe('sec_1');
        });

        it('B2: a multi-data-section only accepts input controls, not location', () => {
            const h = harness();
            h.mutation.onSectionDrop(dropEvent(section('md_1', { type: 'multi-data-section' })));

            expect(h.ctx.sections[0].type).toBe('multi-data-section');
            // A multi-data-section rejecting the Location control is asserted in H2.
        });

        it('B3: dropping a ref-section auto-creates its reference selection field', () => {
            const h = harness();
            h.mutation.onSectionDrop(dropEvent(section('ref_1', { type: 'ref-section' })));

            expect(h.ctx.sections[0].type).toBe('ref-section');
            expect(h.ctx.sections[0].fields).toContain('ref_1-field');
            expect(h.ctx.typeInstance.fields.some((f: any) => f.name === 'ref_1-field' && f.type === 'ref-section-field')).toBe(true);
        });

        it('B4: a section template is added with its fields', () => {
            const h = harness();
            const template = { name: 'tmpl', label: 'Template', type: 'section', is_global: false, fields: [{ name: 'tf', type: 'text' }] };
            h.mutation.onSectionDrop(dropEvent(template));

            expect(h.ctx.sections.length).toBe(1);
            expect(h.ctx.typeInstance.fields.some((f: any) => f.name === 'tf')).toBe(true);
        });

        it('B5: dropping the same non-global template twice produces unique section names', () => {
            const h = harness();
            const template = () => ({ name: 'section_template', label: 'T', type: 'section', is_global: false, fields: [] });
            h.mutation.onSectionDrop(dropEvent(template()));
            h.mutation.onSectionDrop(dropEvent(template(), 1));

            const names = h.ctx.sections.map((s: any) => s.name);
            expect(names.length).toBe(2);
            expect(names[0]).not.toBe(names[1]);
        });

        it('B6: a global section template is applied and removed from the palette', () => {
            const globalTemplate = { name: 'net', label: 'Network', type: 'section', is_global: true, public_id: 3, fields: [{ name: 'ip', type: 'text' }] };
            const h = harness({ globalSectionTemplates: [globalTemplate] });

            h.mutation.onSectionDrop(dropEvent(globalTemplate));

            expect(h.ctx.selectedGlobalSectionTemplates.map((t: any) => t.name)).toContain('net');
            expect(h.ctx.globalSectionTemplates.map((t: any) => t.name)).not.toContain('net');
            expect(h.ctx.typeInstance.global_template_ids).toContain('net');
            expect(h.ctx.typeInstance.fields.some((f: any) => f.name === 'ip')).toBe(true);
        });
    });

    /* ----------------------------------------------- C. REORDER & REMOVE SECTIONS ------------------------------------- */

    describe('C. Reorder & remove sections', () => {

        function twoSections() {
            const a = section('a', { fields: [{ name: 'fa', type: 'text' }] });
            const b = section('b', { fields: [{ name: 'fb', type: 'text' }] });
            const h = harness({
                sections: [a, b],
                typeInstance: { fields: [a.fields[0], b.fields[0]], render_meta: { sections: [a, b], externals: [] }, global_template_ids: [] }
            });
            return { h, a, b };
        }

        it('C1: moving a section updates the order', () => {
            const { h, a, b } = twoSections();
            h.ctx.pendingSectionDropIndex = 0;
            h.ctx.draggedSectionIndex = 1;

            h.mutation.onSectionMoved(b, 'move');

            expect(h.ctx.sections.map((s: any) => s.name)).toEqual(['b', 'a']);
        });

        it('C2: removing a normal section removes the section and its fields', () => {
            const { h, a } = twoSections();
            h.mutation.removeSection(a, 0);

            expect(h.ctx.sections.map((s: any) => s.name)).toEqual(['b']);
            expect(h.ctx.typeInstance.fields.map((f: any) => f.name)).toEqual(['fb']);
        });

        it('C3: removing a global-template section returns it to the palette', () => {
            const glob = section('net', { fields: [] });
            const template = { name: 'net', label: 'Network', public_id: 3, fields: [] };
            const h = harness({
                sections: [glob],
                selectedGlobalSectionTemplates: [template],
                globalSectionTemplates: [],
                typeInstance: { fields: [], render_meta: { sections: [glob], externals: [] }, global_template_ids: ['net'] }
            });

            h.mutation.removeSection(glob, 0);

            expect(h.ctx.globalSectionTemplates.map((t: any) => t.name)).toContain('net');
            expect(h.ctx.selectedGlobalSectionTemplates.map((t: any) => t.name)).not.toContain('net');
            expect(h.ctx.typeInstance.global_template_ids).not.toContain('net');
        });

        it('C4: locked and system sections cannot be moved or removed', () => {
            const h = harness({ lockedSectionNames: ['locked'] });
            expect(h.policy.canMoveSection(section('locked'))).toBe(false);
            expect(h.policy.canRemoveSection(section('locked'))).toBe(false);
            expect(h.policy.canMoveSection(section('dg_gst-x'))).toBe(false);
            expect(h.policy.canRemoveSection(section('dg_gst-x'))).toBe(false);
        });
    });

    /* --------------------------------------------------- D. FIELDS ---------------------------------------------------- */

    describe('D. Fields - add, move, remove', () => {

        it('D1: dropping a basic control adds a field to the section', () => {
            const s = section('s', { fields: [] });
            const h = harness({ sections: [s], typeInstance: { fields: [], render_meta: { sections: [s], externals: [] }, global_template_ids: [] } });

            h.mutation.onFieldDrop(dropEvent({ name: 'txt', type: 'text', label: 'Text' }), s);

            expect(s.fields.map((f: any) => f.name)).toContain('txt');
            expect(h.ctx.typeInstance.fields.some((f: any) => f.name === 'txt')).toBe(true);
        });

        it('D2: moving an existing field relocates it without duplicating', () => {
            const fa = { name: 'fa', type: 'text' };
            const s1 = section('s1', { fields: [fa] });
            const s2 = section('s2', { fields: [] });
            const h = harness({ sections: [s1, s2], typeInstance: { fields: [fa], render_meta: { sections: [s1, s2], externals: [] }, global_template_ids: [] } });

            h.mutation.onFieldDragStart(fa, s1, 0);
            h.mutation.onFieldDrop(dropEvent(fa, 0, 'move'), s2);

            expect(s1.fields.length).toBe(0);
            expect(s2.fields.map((f: any) => f.name)).toEqual(['fa']);
            expect(h.ctx.typeInstance.fields.filter((f: any) => f.name === 'fa').length).toBe(1);
        });

        it('D3: reordering a field within the same section keeps a single copy', () => {
            const f1 = { name: 'f1', type: 'text' };
            const f2 = { name: 'f2', type: 'text' };
            const s = section('s', { fields: [f1, f2] });
            const h = harness({ sections: [s], typeInstance: { fields: [f1, f2], render_meta: { sections: [s], externals: [] }, global_template_ids: [] } });

            h.mutation.onFieldDragStart(f1, s, 0);
            h.mutation.onFieldDrop(dropEvent(f1, 2, 'move'), s);

            expect(s.fields.map((f: any) => f.name)).toEqual(['f2', 'f1']);
        });

        it('D4: removing a field removes it from the section and the type', () => {
            const fa = { name: 'fa', type: 'text' };
            const s = section('s', { fields: [fa] });
            const h = harness({ sections: [s], typeInstance: { fields: [fa], render_meta: { sections: [s], externals: [] }, global_template_ids: [] } });

            h.mutation.removeField(fa, s);

            expect(s.fields.length).toBe(0);
            expect(h.ctx.typeInstance.fields.length).toBe(0);
        });

        it('D5: externalField reports the external links referencing a field', () => {
            const fa = { name: 'fa', type: 'text' };
            const s = section('s', { fields: [fa] });
            const externals = [{ name: 'ext1', label: 'Ext 1', fields: ['fa'] }, { name: 'ext2', label: 'Ext 2', fields: ['other'] }];
            const h = harness({ sections: [s], typeInstance: { fields: [fa], render_meta: { sections: [s], externals }, global_template_ids: [] } });

            const result = h.mutation.externalField(fa);

            expect(result.total).toBe(1);
            expect(result.links.length).toBe(1);
        });

        it('D6: locked / global-template fields cannot be moved or removed', () => {
            const h = harness({ lockedFieldNames: ['locked_field'] });
            expect(h.policy.canMoveField({ name: 'locked_field' })).toBe(false);
            expect(h.policy.canRemoveField({ name: 'locked_field' })).toBe(false);

            const hg = harness({ selectedGlobalSectionTemplates: [{ name: 'g', fields: [{ name: 'gf' }] } as any] });
            expect(hg.policy.canMoveField({ name: 'gf' })).toBe(false);
            expect(hg.policy.canRemoveField({ name: 'gf' })).toBe(false);
        });
    });

    /* ---------------------------------------------- E. EDITING FIELD & SECTION ---------------------------------------- */

    describe('E. Editing field & section config', () => {

        it('E1: changing a field label updates the type instance', () => {
            const fa = { name: 'fa', type: 'text', label: 'Old' };
            const s = section('s', { fields: [fa] });
            const h = harness({ sections: [s], typeInstance: { fields: [fa], render_meta: { sections: [s], externals: [] }, global_template_ids: [] } });

            h.mutation.onFieldChange({ newValue: 'New', inputName: 'label', fieldName: 'fa', previousName: 'fa', elementType: 'text' });

            expect(h.ctx.typeInstance.fields[0].label).toBe('New');
        });

        it('E2: renaming a section updates its identifier', () => {
            const s = section('sec', { fields: [{ name: 'f', type: 'text' }] });
            const h = harness({ sections: [s], typeInstance: { fields: [s.fields[0]], render_meta: { sections: [s], externals: [] }, global_template_ids: [] } });

            h.mutation.onFieldChange({ newValue: 'sec_new', inputName: 'name', fieldName: 'sec', previousName: 'sec', elementType: 'section' });

            expect(h.ctx.typeInstance.render_meta.sections[0].name).toBe('sec_new');
        });

        it('E3: toggling hide adds/removes the field from a multi-data-section hidden_fields', () => {
            const f = { name: 'f1', type: 'text' };
            const md = section('md', { type: 'multi-data-section', fields: [f] });
            const h = harness({ sections: [md], typeInstance: { fields: [f], render_meta: { sections: [md], externals: [] }, global_template_ids: [] } });

            h.mutation.onFieldChange({ inputName: 'hideField', fieldName: 'f1', newValue: true, elementType: 'multi-data-section' });
            expect((h.ctx.typeInstance.render_meta.sections[0] as any).hidden_fields).toContain('f1');

            h.mutation.onFieldChange({ inputName: 'hideField', fieldName: 'f1', newValue: false, elementType: 'multi-data-section' });
            expect((h.ctx.typeInstance.render_meta.sections[0] as any).hidden_fields).not.toContain('f1');
        });

        it('E4: renaming a hidden field keeps it hidden under the new name', () => {
            const f = { name: 'f1', type: 'text' };
            const md: any = section('md', { type: 'multi-data-section', fields: [f] });
            md.hidden_fields = ['f1'];
            const h = harness({ sections: [md], typeInstance: { fields: [f], render_meta: { sections: [md], externals: [] }, global_template_ids: [] } });

            h.mutation.onFieldChange({ newValue: 'f1_new', inputName: 'name', fieldName: 'f1', previousName: 'f1', elementType: 'text' });

            expect((h.ctx.typeInstance.render_meta.sections[0] as any).hidden_fields).toEqual(['f1_new']);
            expect(h.ctx.typeInstance.fields[0].name).toBe('f1_new');
        });

        it('E5: a duplicate field marks fields disabled and records the active duplicate', () => {
            const h = harness();
            h.mutation.onFieldChange({ isDuplicate: true, elementType: 'field' }, 1, 2);

            expect(h.ctx.disableFields).toBe(true);
            expect(h.ctx.activeDuplicateField).toEqual({ sectionIndex: 1, fieldIndex: 2 });

            h.mutation.onFieldChange({ isDuplicate: false, elementType: 'field' });
            expect(h.ctx.disableFields).toBe(false);
        });

        it('E6: selectable_as_parent is applied to the type instance', () => {
            const h = harness();
            h.mutation.onFieldChange({ inputName: 'selectable_as_parent', newValue: true });
            expect(h.ctx.typeInstance.selectable_as_parent).toBe(true);
        });
    });

    /* ------------------------------------------------ F. VALIDATION & HIGHLIGHT --------------------------------------- */

    describe('F. Validation & highlighting', () => {

        it('F1: a field with an empty name or label is highlighted', () => {
            const h = harness();
            const s = section('s');
            expect(h.highlight.isFieldHighlighted({ name: '', label: 'x', type: 'text' }, s)).toBe(true);
            expect(h.highlight.isFieldHighlighted({ name: 'ok', label: '', type: 'text' }, s)).toBe(true);
            expect(h.highlight.isFieldHighlighted({ name: 'ok', label: 'ok', type: 'text' }, s)).toBe(false);
        });

        it('F2: duplicate field identifiers are highlighted', () => {
            const dupA = { name: 'dup', label: 'A', type: 'text' };
            const dupB = { name: 'dup', label: 'B', type: 'text' };
            const s = section('s', { fields: [dupA, dupB] });
            const h = harness({ sections: [s], typeInstance: { fields: [dupA, dupB], render_meta: { sections: [s], externals: [] }, global_template_ids: [] } });

            expect(h.highlight.isFieldHighlighted(dupA, s)).toBe(true);
            expect(h.highlight.isFieldHighlighted(dupB, s)).toBe(true);
        });

        it('F3: reserved dg-/dg_ prefixes are flagged for user sections and fields', () => {
            const h = harness();
            expect(h.highlight.isSectionHighlighted(section('dg-network'))).toBe(true);
            expect(h.highlight.isSectionHighlighted(section('dg_network'))).toBe(true);
            expect(h.highlight.isFieldHighlighted({ name: 'dg-x', label: 'x', type: 'text' }, section('s'))).toBe(true);
        });

        it('F4: a ref field without ref-types or complete summaries is highlighted', () => {
            const h = harness();
            const s = section('s');
            expect(h.highlight.isFieldHighlighted({ type: 'ref', name: 'r', label: 'R', ref_types: [], summaries: [] }, s)).toBe(true);
            expect(h.highlight.isFieldHighlighted(
                { type: 'ref', name: 'r', label: 'R', ref_types: [1], summaries: [{ type_id: 1, line: 'x' }] }, s)).toBe(false);
        });

        it('F5: a section without fields disables the save state and highlights its header', () => {
            const empty = section('empty', { fields: [] });
            const h = harness({ sections: [empty], typeInstance: { fields: [], render_meta: { sections: [empty], externals: [] }, global_template_ids: [] } });

            h.highlight.updateSectionFieldStatus();
            expect(h.validationService.setSectionWithoutFieldState).toHaveBeenCalledWith(false);
            expect(h.highlight.getSectionHeaderClass(empty)['highlight-section-header']).toBe(true);
        });

        it('F6: a ref-section without a target reference is flagged', () => {
            const h = harness();
            expect(h.highlight.isSectionHighlighted({ name: 'rs', label: 'RS', type: 'ref-section', fields: [], reference: {} })).toBe(true);
            expect(h.highlight.isSectionHighlighted(
                { name: 'rs', label: 'RS', type: 'ref-section', fields: [], reference: { type_id: 1, section_name: 's' } })).toBe(false);
        });
    });

    /* ------------------------------------------- G. LOCKED / GLOBAL / SYSTEM ------------------------------------------ */

    describe('G. Locked / global / system content', () => {

        it('G1: a global-template section is not editable and never highlighted', () => {
            const h = harness({
                selectedGlobalSectionTemplates: [{ name: 'g', fields: [{ name: 'gf' }] } as any],
                typeInstance: { fields: [], render_meta: { sections: [], externals: [] }, global_template_ids: ['g'] }
            });
            const glob = section('g', { fields: [{ name: 'gf', type: 'text' }] });

            expect(h.policy.canEditSection(glob)).toBe(false);
            expect(h.policy.canMoveSection(glob)).toBe(true);       // global sections may be moved / removed back to palette
            expect(h.policy.canRemoveSection(glob)).toBe(true);
            expect(h.highlight.isSectionHighlighted(glob)).toBe(false);
        });

        it('G2: the system location field keeps its reserved dg_location name without being flagged', () => {
            const h = harness();
            const location = { name: 'dg_location', label: 'Location', type: 'location' };
            expect(h.highlight.isFieldHighlighted(location, section('s'))).toBe(false);
        });
    });

    /* ---------------------------------------------------- H. SPECIAL CONTROLS ----------------------------------------- */

    describe('H. Special controls (location)', () => {

        it('H1: a location field is accepted into a normal section', () => {
            const s = section('s', { fields: [] });
            const h = harness({ sections: [s], typeInstance: { fields: [], render_meta: { sections: [s], externals: [] }, global_template_ids: [] } });

            h.mutation.onFieldDrop(dropEvent({ name: 'dg_location', type: 'location' }), s);
            expect(s.fields.length).toBe(1);
        });

        it('H2: a location field is rejected from a multi-data-section', () => {
            const md = section('md', { type: 'multi-data-section', fields: [] });
            const h = harness({ sections: [md], typeInstance: { fields: [], render_meta: { sections: [md], externals: [] }, global_template_ids: [] } });

            h.mutation.onFieldDrop(dropEvent({ name: 'dg_location', type: 'location' }), md);
            expect(md.fields.length).toBe(0);
            expect(h.ctx.typeInstance.fields.some((f: any) => f.type === 'location')).toBe(false);
        });

        it('H3: in Edit mode an in-use location field/section cannot be deleted', () => {
            const location = { name: 'dg_location', type: 'location' };
            const s = section('s', { fields: [location] });
            const h = harness({ mode: CmdbMode.Edit, sections: [s], typeInstance: { fields: [location], render_meta: { sections: [s], externals: [] }, global_template_ids: [] } });

            h.deps.deletionGuard.isLocationField.and.returnValue(true);
            h.deps.deletionGuard.canDelete.and.returnValue(false);
            h.deps.deletionGuard.sectionContainsLocationField.and.returnValue(true);

            h.mutation.removeField(location, s);
            expect(s.fields.length).toBe(1);

            h.mutation.removeSection(s, 0);
            expect(h.ctx.sections.length).toBe(1);
        });
    });

    /* ---------------------------------------------------- I. PREVIEW / DIAGNOSTIC ------------------------------------- */

    describe('I. Preview / Diagnostic', () => {

        it('I1/I2: preview and diagnostic open a modal seeded with the sections', () => {
            const modalRefPreview = { componentInstance: {} as any };
            const modalRefDiag = { componentInstance: {} as any };
            const modalService = jasmine.createSpyObj('NgbModal', ['open']);
            modalService.open.and.returnValues(modalRefPreview, modalRefDiag);
            const sections = [section('s')];

            BuilderUtils.openPreview(modalService, sections);
            BuilderUtils.openDiagnostic(modalService, sections);

            expect(modalService.open).toHaveBeenCalledTimes(2);
            expect(modalRefPreview.componentInstance.sections).toBe(sections);
            expect(modalRefDiag.componentInstance.data).toBe(sections);
        });
    });

    /* ------------------------------------------------ J. SAVE / STEP PROGRESSION -------------------------------------- */

    describe('J. Save / step progression', () => {

        it('J1: a fully valid type reports no highlight and all sections have fields', () => {
            const s = section('s', { fields: [{ name: 'f', label: 'F', type: 'text' }] });
            const h = harness({ sections: [s], typeInstance: { fields: [s.fields[0]], render_meta: { sections: [s], externals: [] }, global_template_ids: [] } });

            h.highlight.updateHighlightState();

            expect(h.validationService.setSectionHighlightState).toHaveBeenCalledWith(false);
            expect(h.validationService.setFieldHighlightState).toHaveBeenCalledWith(false);
            expect(h.validationService.setSectionWithoutFieldState).toHaveBeenCalledWith(true);
        });

        it('J2: introducing an error flips the highlight state', () => {
            const bad = section('dg-bad', { fields: [{ name: 'f', label: 'F', type: 'text' }] });
            const h = harness({ sections: [bad], typeInstance: { fields: [bad.fields[0]], render_meta: { sections: [bad], externals: [] }, global_template_ids: [] } });

            h.highlight.updateHighlightState();
            expect(h.validationService.setSectionHighlightState).toHaveBeenCalledWith(true);
        });
    });

    /* ----------------------------------------------------- K. EDIT MODE ----------------------------------------------- */

    describe('K. Edit-mode specifics', () => {

        it('K1: a freshly added field is treated as new (create mode in its editor)', () => {
            const newField = { name: 'nf', type: 'text' };
            expect(BuilderUtils.isNewField(newField, [newField] as any)).toBe(true);
            expect(BuilderUtils.isNewField({ name: 'existing', type: 'text' }, [] as any)).toBe(false);
        });

        it('K3: reloading rebuilds the sections projection from the type instance (order + fields)', () => {
            const f1 = { name: 'f1', type: 'text' };
            const f2 = { name: 'f2', type: 'text' };
            const s1 = { name: 's1', label: 'S1', type: 'section', fields: ['f1'] };
            const s2 = { name: 's2', label: 'S2', type: 'section', fields: ['f2'] };
            const h = harness({ typeInstance: { fields: [f1, f2], render_meta: { sections: [s1, s2], externals: [] }, global_template_ids: [] } });

            h.mutation.syncSectionsFromModel();

            expect(h.ctx.sections.map((s: any) => s.name)).toEqual(['s1', 's2']);
            expect(h.ctx.sections[0].fields).toEqual([f1]);
            expect(h.ctx.sections[1].fields).toEqual([f2]);
        });

    });
});
