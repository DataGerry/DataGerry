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
/* ------------------------------------------------------------------------------------------------------------------ */

/**
 * What the builder flags as invalid, and what it reports to the wizard.
 *
 * These decisions are what gate Next and Save: the helper pushes `setSectionHighlightState`,
 * `setFieldHighlightState` and `setSectionWithoutFieldState` into the app-wide `ValidationService`,
 * and `BuilderWizardBlockingState` turns all three into one `blocked` flag. A highlight rule that
 * silently stops firing therefore does not look broken - it just makes an invalid type savable.
 */
describe('Builder highlighting', () => {

    interface Harness {
        ctx: BuilderContext & { typeInstance: any };
        policy: BuilderInteractionPolicy;
        highlight: BuilderHighlightHelper;
        validationService: any;
    }

    function harness(seed: any = {}): Harness {
        const sections = seed.sections ?? [];
        const typeInstance: any = seed.typeInstance ?? {
            fields: sections.flatMap((s: any) => s.fields ?? []).filter((f: any) => typeof f === 'object'),
            render_meta: { sections, externals: [] },
            global_template_ids: []
        };

        const ctx: BuilderContext & { typeInstance: any } = {
            sections,
            schema: new CmdbTypeSchemaAdapter(typeInstance),
            typeInstance,
            newSections: seed.newSections ?? [],
            newFields: seed.newFields ?? [],
            globalSectionTemplates: [],
            selectedGlobalSectionTemplates: seed.selectedGlobalSectionTemplates ?? [],
            lockedSectionNames: seed.lockedSectionNames ?? [],
            lockedFieldNames: seed.lockedFieldNames ?? [],
            disableFields: seed.disableFields ?? false,
            mode: seed.mode ?? CmdbMode.Create,
            activeIndex: null,
            draggedSectionIndex: null,
            pendingSectionDropIndex: null,
            draggedField: null,
            activeDuplicateField: seed.activeDuplicateField ?? null,
            prevSectionHighlighted: false,
            prevFieldHighlighted: false,
            sectionReference: null,
            initialFieldNames: seed.initialFieldNames ?? null,
            initialIdentifier: ''
        };

        const validationService = jasmine.createSpyObj('ValidationService',
            ['setSectionHighlightState', 'setFieldHighlightState', 'setSectionWithoutFieldState']);

        const policyContext = (): BuilderInteractionPolicyContext => {
            const applied = ctx.selectedGlobalSectionTemplates ?? [];
            return {
                selectedGlobalSectionTemplates: applied,
                globalTemplateIds: ctx.schema.readGlobalTemplateIds(),
                globalFieldNames: applied.flatMap(t => (t?.fields ?? []).map((f: any) => f?.name)),
                schemaLockedSectionNames: ctx.lockedSectionNames ?? [],
                schemaLockedFieldNames: ctx.lockedFieldNames ?? []
            };
        };

        const policy = new BuilderInteractionPolicy(policyContext);
        const highlight = new BuilderHighlightHelper(ctx, policy, validationService);

        return { ctx, policy, highlight, validationService };
    }

    function section(name: string, extra: any = {}): any {
        return { name, label: extra.label ?? name.toUpperCase(), type: extra.type ?? 'section', fields: extra.fields ?? [], ...extra };
    }

    function field(name: string, extra: any = {}): any {
        return { name, label: extra.label ?? name.toUpperCase(), type: extra.type ?? 'text', ...extra };
    }

    /* ================================================================================================================ */
    /*                                               SECTION HIGHLIGHTING                                               */
    /* ================================================================================================================ */

    describe('a section is highlighted when', () => {

        it('it has no identifier', () => {
            const s = section('', { fields: [field('a')] });
            expect(harness({ sections: [s] }).highlight.isSectionHighlighted(s)).toBeTrue();
        });


        it('it has no label', () => {
            const s = section('s', { label: '', fields: [field('a')] });
            expect(harness({ sections: [s] }).highlight.isSectionHighlighted(s)).toBeTrue();
        });


        it('another section shares its identifier', () => {
            const first = section('dup', { fields: [field('a')] });
            const second = section('dup', { fields: [field('b')] });
            const h = harness({ sections: [first, second] });

            expect(h.highlight.isSectionHighlighted(first)).toBeTrue();
            expect(h.highlight.isSectionHighlighted(second)).toBeTrue();
        });


        it('one of its fields is invalid', () => {
            const s = section('s', { fields: [field('a'), field('', { label: '' })] });
            expect(harness({ sections: [s] }).highlight.isSectionHighlighted(s)).toBeTrue();
        });


        it('a ref-section has no reference target', () => {
            const s = section('r', { type: 'ref-section', fields: ['r-field'] });
            expect(harness({ sections: [s] }).highlight.isSectionHighlighted(s)).toBeTrue();
        });


        it('a ref-section names a type but no section', () => {
            const s = section('r', { type: 'ref-section', fields: ['r-field'], reference: { type_id: 4, section_name: '' } });
            expect(harness({ sections: [s] }).highlight.isSectionHighlighted(s)).toBeTrue();
        });
    });


    describe('a section is not highlighted when', () => {

        it('it is complete and its fields are valid', () => {
            const s = section('s', { fields: [field('a')] });
            expect(harness({ sections: [s] }).highlight.isSectionHighlighted(s)).toBeFalse();
        });


        it('a ref-section has a complete reference', () => {
            const s = section('r', { type: 'ref-section', fields: ['r-field'], reference: { type_id: 4, section_name: 'other' } });
            expect(harness({ sections: [s] }).highlight.isSectionHighlighted(s)).toBeFalse();
        });


        /** Sections we define - global templates, special-type schema, dg_gst- system sections - are trusted. */
        it('it is an applied global template, even with a broken field', () => {
            const applied = { name: 'gt', label: 'GT', public_id: 1, fields: [] };
            const s = section('gt', { fields: [field('', { label: '' })] });

            expect(harness({ sections: [s], selectedGlobalSectionTemplates: [applied] })
                .highlight.isSectionHighlighted(s)).toBeFalse();
        });


        it('it is schema-locked by a special type', () => {
            const s = section('locked', { label: '', fields: [] });
            expect(harness({ sections: [s], lockedSectionNames: ['locked'] })
                .highlight.isSectionHighlighted(s)).toBeFalse();
        });


        it('it is a dg_gst- system section', () => {
            const s = section('dg_gst-x', { label: '', fields: [] });
            expect(harness({ sections: [s] }).highlight.isSectionHighlighted(s)).toBeFalse();
        });
    });

    /* ================================================================================================================ */
    /*                                       RESERVED PREFIX - MODE DEPENDENT                                           */
    /* ================================================================================================================ */

    /**
     * The reserved `dg_`/`dg-` namespace is only rejected where the editor actually applies the
     * validator - i.e. where the identifier is mounted in Create mode. `disableControlOnEdit` clears
     * those validators in Edit mode, so flagging a saved identifier would permanently block saving a
     * record created before the rule existed. Relations in particular may hold such names.
     */
    describe('the reserved dg_ prefix', () => {

        it('is flagged on a section being authored (Create)', () => {
            const s = section('dg_custom', { fields: [field('a')] });
            expect(harness({ sections: [s], mode: CmdbMode.Create }).highlight.isSectionHighlighted(s)).toBeTrue();
        });


        it('is NOT flagged on a saved section (Edit)', () => {
            const s = section('dg_custom', { fields: [field('a')] });
            expect(harness({ sections: [s], mode: CmdbMode.Edit }).highlight.isSectionHighlighted(s)).toBeFalse();
        });


        it('is flagged again on a section added during an edit', () => {
            const s = section('dg_custom', { fields: [field('a')] });
            expect(harness({ sections: [s], mode: CmdbMode.Edit, newSections: [s] })
                .highlight.isSectionHighlighted(s)).toBeTrue();
        });


        it('is flagged on a field being authored (Create)', () => {
            const f = field('dg_mine');
            expect(harness({ sections: [section('s', { fields: [f] })], mode: CmdbMode.Create })
                .highlight.isFieldHighlighted(f)).toBeTrue();
        });


        it('is NOT flagged on a saved field (Edit)', () => {
            const f = field('dg_mine');
            const h = harness({
                sections: [section('s', { fields: [f] })],
                mode: CmdbMode.Edit,
                initialFieldNames: new Set(['dg_mine'])
            });

            expect(h.highlight.isFieldHighlighted(f)).toBeFalse();
        });


        it('is flagged again on a field added during an edit', () => {
            const f = field('dg_mine');
            const h = harness({
                sections: [section('s', { fields: [f] })],
                mode: CmdbMode.Edit,
                initialFieldNames: new Set(['something-else'])
            });

            expect(h.highlight.isFieldHighlighted(f)).toBeTrue();
        });


        /** The Location control ships as the system-owned `dg_location`, which the user cannot edit. */
        it('never flags the system location field', () => {
            const f = field('dg_location', { type: 'location' });
            expect(harness({ sections: [section('s', { fields: [f] })], mode: CmdbMode.Create })
                .highlight.isFieldHighlighted(f)).toBeFalse();
        });
    });

    /* ================================================================================================================ */
    /*                                                FIELD HIGHLIGHTING                                                */
    /* ================================================================================================================ */

    describe('a field is highlighted when', () => {

        it('it has no identifier', () => {
            const f = field('');
            expect(harness({ sections: [section('s', { fields: [f] })] }).highlight.isFieldHighlighted(f)).toBeTrue();
        });


        it('it has no label', () => {
            const f = field('a', { label: '' });
            expect(harness({ sections: [section('s', { fields: [f] })] }).highlight.isFieldHighlighted(f)).toBeTrue();
        });


        it('another field shares its identifier', () => {
            const first = field('dup');
            const second = field('dup');
            const h = harness({ sections: [section('s', { fields: [first, second] })] });

            expect(h.highlight.isFieldHighlighted(first)).toBeTrue();
            expect(h.highlight.isFieldHighlighted(second)).toBeTrue();
        });


        it('a duplicate identifier spans two different sections', () => {
            const first = field('dup');
            const second = field('dup');
            const h = harness({
                sections: [section('a', { fields: [first] }), section('b', { fields: [second] })]
            });

            expect(h.highlight.isFieldHighlighted(first)).toBeTrue();
        });


        it('a ref field has no ref_types', () => {
            const f = field('r', { type: 'ref', ref_types: [], summaries: [] });
            expect(harness({ sections: [section('s', { fields: [f] })] }).highlight.isFieldHighlighted(f)).toBeTrue();
        });


        it('a ref field has an incomplete summary line', () => {
            const f = field('r', { type: 'ref', ref_types: [2], summaries: [{ type_id: 2, line: '   ' }] });
            expect(harness({ sections: [section('s', { fields: [f] })] }).highlight.isFieldHighlighted(f)).toBeTrue();
        });


        it('a locked field has a duplicate identifier', () => {
            const first = field('dup');
            const second = field('dup');
            const h = harness({
                sections: [section('s', { fields: [first, second] })],
                lockedFieldNames: ['dup']
            });

            expect(h.highlight.isFieldHighlighted(first)).toBeTrue();
        });
    });


    describe('a field is not highlighted when', () => {

        it('it is complete', () => {
            const f = field('a');
            expect(harness({ sections: [section('s', { fields: [f] })] }).highlight.isFieldHighlighted(f)).toBeFalse();
        });


        it('a ref field is fully configured', () => {
            const f = field('r', { type: 'ref', ref_types: [2], summaries: [{ type_id: 2, line: 'x' }] });
            expect(harness({ sections: [section('s', { fields: [f] })] }).highlight.isFieldHighlighted(f)).toBeFalse();
        });


        /** Section entries are field *names* until the canvas hydrates them; a string is not a field. */
        it('the entry is still an unhydrated field name', () => {
            expect(harness().highlight.isFieldHighlighted('not-hydrated-yet')).toBeFalse();
            expect(harness().highlight.isFieldHighlighted(null)).toBeFalse();
            expect(harness().highlight.isFieldHighlighted(undefined)).toBeFalse();
        });


        it('it sits inside a section the user cannot edit', () => {
            const f = field('', { label: '' });
            const s = section('locked', { fields: [f] });

            expect(harness({ sections: [s], lockedSectionNames: ['locked'] })
                .highlight.isFieldHighlighted(f, s)).toBeFalse();
        });


        /** A schema-locked field is not user-editable, so only a real identifier clash matters. */
        it('a locked field is incomplete but unique', () => {
            const f = field('locked-field', { label: '' });
            const h = harness({
                sections: [section('s', { fields: [f] })],
                lockedFieldNames: ['locked-field']
            });

            expect(h.highlight.isFieldHighlighted(f)).toBeFalse();
        });
    });

    /* ================================================================================================================ */
    /*                                       WHAT THE WIZARD IS TOLD (SAVE GATE)                                        */
    /* ================================================================================================================ */

    describe('reporting to the wizard', () => {

        it('reports both highlight states and the section-without-fields state', () => {
            const h = harness({ sections: [section('s', { fields: [field('a')] })] });

            h.highlight.updateHighlightState();

            expect(h.validationService.setSectionHighlightState).toHaveBeenCalledWith(false);
            expect(h.validationService.setFieldHighlightState).toHaveBeenCalledWith(false);
            expect(h.validationService.setSectionWithoutFieldState).toHaveBeenCalledWith(true);
        });


        it('reports a highlighted section and field when one is broken', () => {
            const h = harness({ sections: [section('s', { fields: [field('', { label: '' })] })] });

            h.highlight.updateHighlightState();

            expect(h.validationService.setSectionHighlightState).toHaveBeenCalledWith(true);
            expect(h.validationService.setFieldHighlightState).toHaveBeenCalledWith(true);
        });


        /** `setSectionWithoutFieldState(true)` means "every section has fields" despite the name. */
        it('reports false while any section is still empty', () => {
            const h = harness({ sections: [section('a', { fields: [field('x')] }), section('b', { fields: [] })] });

            h.highlight.updateSectionFieldStatus();

            expect(h.validationService.setSectionWithoutFieldState).toHaveBeenCalledWith(false);
        });


        it('reports true for an empty canvas, which has no offending section', () => {
            const h = harness({ sections: [] });

            h.highlight.updateSectionFieldStatus();

            expect(h.validationService.setSectionWithoutFieldState).toHaveBeenCalledWith(true);
        });


        /**
         * `ngAfterViewChecked` calls this on every single change-detection pass, so it must only push
         * when the answer actually changed - otherwise the wizard's buttons churn on every tick.
         */
        it('pushes only when the highlight state changes', () => {
            const broken = field('', { label: '' });
            const s = section('s', { fields: [broken] });
            const h = harness({ sections: [s] });

            h.highlight.checkAndUpdateHighlightState();
            expect(h.validationService.setSectionHighlightState).toHaveBeenCalledTimes(1);

            h.highlight.checkAndUpdateHighlightState();
            expect(h.validationService.setSectionHighlightState)
                .withContext('nothing changed, so nothing is pushed')
                .toHaveBeenCalledTimes(1);

            broken.name = 'fixed';
            broken.label = 'Fixed';
            h.highlight.checkAndUpdateHighlightState();
            expect(h.validationService.setSectionHighlightState).toHaveBeenCalledTimes(2);
            expect(h.validationService.setSectionHighlightState).toHaveBeenCalledWith(false);
        });


        /**
         * The memo compares against what was *last reported*, and the mutation paths report through
         * `updateHighlightState` rather than through the memo. If that direct call does not refresh
         * the record, the record and the wizard drift apart - and the next real change that happens
         * to match the stale record is dropped on the floor.
         *
         * The route in: a field editor that writes straight onto the field object and emits nothing
         * (the Location editor does this with its label, the Reference editor with `ref_types` and
         * `summaries`), so `ngAfterViewChecked` is the only thing that can notice.
         */
        it('still reports a change that arrives after a direct update', () => {
            const silent = field('dg_location', { label: 'Location', type: 'location' });
            const broken = field('', { label: '' });
            const h = harness({ sections: [section('s', { fields: [silent, broken] })] });

            // the unnamed field is noticed through the memo, which records "highlighted"
            h.highlight.checkAndUpdateHighlightState();
            expect(h.validationService.setFieldHighlightState).toHaveBeenCalledWith(true);

            // the user fixes it; a mutation path reports directly, without going through the memo
            broken.name = 'fixed';
            broken.label = 'Fixed';
            h.highlight.updateHighlightState();
            expect(h.validationService.setFieldHighlightState).toHaveBeenCalledWith(false);

            // an editor now empties a label in place and emits nothing
            silent.label = '';
            h.validationService.setFieldHighlightState.calls.reset();
            h.highlight.checkAndUpdateHighlightState();

            expect(h.highlight.isAnyFieldHighlighted())
                .withContext('the field really is invalid').toBeTrue();
            expect(h.validationService.setFieldHighlightState)
                .withContext('and the wizard has to hear about it').toHaveBeenCalledWith(true);
        });


        it('remembers the last reported state', () => {
            const h = harness({ sections: [section('s', { fields: [field('', { label: '' })] })] });

            h.highlight.checkAndUpdateHighlightState();

            expect(h.ctx.prevSectionHighlighted).toBeTrue();
            expect(h.ctx.prevFieldHighlighted).toBeTrue();
        });


        it('aggregates across all sections', () => {
            const h = harness({
                sections: [
                    section('ok', { fields: [field('a')] }),
                    section('bad', { fields: [field('', { label: '' })] })
                ]
            });

            expect(h.highlight.isAnySectionHighlighted()).toBeTrue();
            expect(h.highlight.isAnyFieldHighlighted()).toBeTrue();
        });
    });

    /* ================================================================================================================ */
    /*                                          LOCKING WHILE A FIELD IS UNNAMED                                        */
    /* ================================================================================================================ */

    describe('the unnamed-field lock', () => {

        it('lists every field left without an identifier', () => {
            const h = harness({
                sections: [
                    section('a', { fields: [field('x'), field('')] }),
                    section('b', { fields: [field('  ')] })
                ]
            });

            expect(h.highlight.checkEmptyFields()).toEqual([
                { sectionIndex: 0, fieldIndex: 1 },
                { sectionIndex: 1, fieldIndex: 0 }
            ]);
        });


        it('locks the builder while any field is unnamed', () => {
            const h = harness({ sections: [section('a', { fields: [field('')] })] });
            expect(h.highlight.isLocked()).toBeTrue();
        });


        it('does not lock once every field is named', () => {
            const h = harness({ sections: [section('a', { fields: [field('x')] })] });
            expect(h.highlight.isLocked()).toBeFalse();
        });


        /**
         * Counter-intuitive but deliberate: this answers "must this editor be greyed out?", so it is
         * TRUE for every field *except* the unnamed one the user still has to fix.
         */
        it('greys out every editor except the one that must be fixed', () => {
            const h = harness({ sections: [section('a', { fields: [field('x'), field('')] })] });

            expect(h.highlight.isEmptyFielsExist(0, 1)).withContext('the offending field stays editable').toBeFalse();
            expect(h.highlight.isEmptyFielsExist(0, 0)).withContext('every other editor is greyed out').toBeTrue();
        });


        it('greys nothing out when no field is unnamed', () => {
            const h = harness({ sections: [section('a', { fields: [field('x')] })] });
            expect(h.highlight.isEmptyFielsExist(0, 0)).toBeFalse();
        });
    });

    /* ================================================================================================================ */
    /*                                        THE DUPLICATE-IDENTIFIER LATCH                                            */
    /* ================================================================================================================ */

    describe('the duplicate-identifier latch', () => {

        it('greys out every editor except the one holding the duplicate', () => {
            const h = harness({
                sections: [section('a', { fields: [field('x'), field('y')] })],
                disableFields: true,
                activeDuplicateField: { sectionIndex: 0, fieldIndex: 1 }
            });

            expect(h.highlight.isConfigEditDisabled(0, 1)).withContext('the offending editor stays open').toBeFalse();
            expect(h.highlight.isConfigEditDisabled(0, 0)).toBeTrue();
        });


        it('greys out nothing while the latch is open', () => {
            const h = harness({ sections: [section('a', { fields: [field('x')] })] });
            expect(h.highlight.isConfigEditDisabled(0, 0)).toBeFalse();
        });
    });

    /* ================================================================================================================ */
    /*                                              DERIVED PRESENTATION                                                */
    /* ================================================================================================================ */

    describe('derived CSS state', () => {

        it('marks a section header for a global template', () => {
            const applied = { name: 'gt', label: 'GT', public_id: 1, fields: [] };
            const s = section('gt', { fields: [field('a')] });
            const h = harness({ sections: [s], selectedGlobalSectionTemplates: [applied] });

            expect(h.highlight.getSectionHeaderClass(s)['global-section-item']).toBeTrue();
        });


        it('marks a section header while the section has no fields', () => {
            const s = section('s', { fields: [] });
            expect(harness({ sections: [s] }).highlight.getSectionHeaderClass(s)['highlight-section-header']).toBeTrue();
        });


        it('marks a section header while the section is invalid', () => {
            const s = section('', { fields: [field('a')] });
            expect(harness({ sections: [s] }).highlight.getSectionHeaderClass(s)['highlight-section-header']).toBeTrue();
        });


        it('leaves a healthy section header unmarked', () => {
            const s = section('s', { fields: [field('a')] });
            const classes = harness({ sections: [s] }).highlight.getSectionHeaderClass(s);

            expect(classes['highlight-section-header']).toBeFalse();
            expect(classes['global-section-item']).toBeFalse();
        });


        /**
         * Deliberately a stable object reference, mutated in place: it used to feed an `[ngClass]` on
         * every draggable control, and a fresh object per check re-ran NgClass' diff each tick.
         */
        it('keeps one object for the draggable state and mutates it in place', () => {
            const h = harness({ sections: [section('s', { fields: [field('a')] })] });

            const first = h.highlight.getDraggableItemClass();
            expect(first.disabled).toBeFalse();

            h.ctx.disableFields = true;
            const second = h.highlight.getDraggableItemClass();

            expect(second).toBe(first);
            expect(second.disabled).toBeTrue();
        });


        it('disables dragging while a section is highlighted', () => {
            const h = harness({ sections: [section('', { fields: [field('a')] })] });
            expect(h.highlight.getDraggableItemClass().disabled).toBeTrue();
        });
    });

    /* ================================================================================================================ */
    /*                                        BLOCKING A DRAG THAT MUST NOT START                                       */
    /* ================================================================================================================ */

    describe('blocking a field drag', () => {

        function dragEvent(): any {
            return jasmine.createSpyObj('DragEvent', ['stopPropagation', 'preventDefault']);
        }

        function expectBlocked(h: Harness, s: any, blocked: boolean): void {
            const event = dragEvent();
            h.highlight.preventDragForAllFields(event, s);

            expect(event.preventDefault).toHaveBeenCalledTimes(blocked ? 1 : 0);
            expect(event.stopPropagation).toHaveBeenCalledTimes(blocked ? 1 : 0);
        }

        it('blocks while a field in the section is invalid', () => {
            const s = section('s', { fields: [field('a'), field('b', { label: '' })] });
            expectBlocked(harness({ sections: [s] }), s, true);
        });


        it('blocks while any field anywhere is unnamed', () => {
            const clean = section('clean', { fields: [field('a')] });
            const dirty = section('dirty', { fields: [field('')] });
            expectBlocked(harness({ sections: [clean, dirty] }), clean, true);
        });


        it('blocks while the duplicate-identifier latch is closed', () => {
            const s = section('s', { fields: [field('a')] });
            expectBlocked(harness({ sections: [s], disableFields: true }), s, true);
        });


        it('blocks while another section is highlighted', () => {
            const clean = section('clean', { fields: [field('a')] });
            const broken = section('', { fields: [field('b')] });
            expectBlocked(harness({ sections: [clean, broken] }), clean, true);
        });


        it('allows the drag when everything is valid', () => {
            const s = section('s', { fields: [field('a')] });
            expectBlocked(harness({ sections: [s] }), s, false);
        });
    });
});
