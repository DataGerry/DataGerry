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
/* ------------------------------------------------------------------------------------------------------------------ */

/**
 * Drag and drop, exhaustively: dropping sections and fields, reordering both, and every guard that
 * decides a drag must not take effect.
 *
 * None of this is reachable by the AOT check or by a rendered-component test - ngx-drag-drop only
 * ever hands the builder a `DndDropEvent`, so the drop handlers are driven directly with the events
 * the directive would emit. The section reorder in particular is a **two-phase** protocol
 * (`dndDrop` records an index and returns, `dndMoved` performs the splice); collapsing it into one
 * phase is what let the old relation fork duplicate a section on every reorder.
 */
describe('Builder drag and drop', () => {

    interface Harness {
        ctx: BuilderContext & { typeInstance: any };
        policy: BuilderInteractionPolicy;
        highlight: BuilderHighlightHelper;
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
        const typeInstance: any = seed.typeInstance
            ?? { fields: [], render_meta: { sections: [], externals: [] }, global_template_ids: [] };

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

        return { ctx, policy, highlight, mutation, deps, validationService };
    }

    function section(name: string, extra: any = {}): any {
        return { name, label: extra.label ?? name.toUpperCase(), type: extra.type ?? 'section', fields: extra.fields ?? [], ...extra };
    }

    function field(name: string, extra: any = {}): any {
        return { name, label: extra.label ?? name.toUpperCase(), type: extra.type ?? 'text', ...extra };
    }

    /**
     * The event shape ngx-drag-drop hands `(dndDrop)`. `index` is undefined when dropped on empty
     * space.
     *
     * The payload is deliberately round-tripped through JSON, because that is exactly what the
     * library does: `JSON.stringify` into `dataTransfer` on dragstart, `JSON.parse` back out on drop.
     * A drop handler therefore NEVER receives the array entry that was dragged. Passing the live
     * object here instead is the easiest way to write a green reorder test for a feature that
     * duplicates the row in a real browser — which is precisely the bug this suite missed once.
     */
    function dropEvent(data: any, index?: number, dropEffect: string = 'copy'): any {
        return {
            data: data === undefined ? data : JSON.parse(JSON.stringify(data)),
            index,
            dropEffect,
            event: { preventDefault: () => { } }
        };
    }

    /**
     * Seeds a type whose model already holds the given sections and their fields.
     *
     * The canvas projection and the model keep **separate arrays** over the same section objects,
     * exactly as `syncSectionsFromModel` leaves them - so a helper that updates only one of the two
     * is caught here rather than passing because both names point at one array.
     */
    function seeded(sections: Array<any>): any {
        const fields = sections.flatMap(s => s.fields ?? []).filter(f => typeof f === 'object');
        return {
            sections: [...sections],
            typeInstance: {
                fields,
                render_meta: { sections, externals: [] },
                global_template_ids: []
            }
        };
    }

    /* ================================================================================================================ */
    /*                                                  SECTION DROP                                                    */
    /* ================================================================================================================ */

    describe('dropping a section', () => {

        it('inserts at the drop index and records it as a new section', () => {
            const h = harness(seeded([section('a'), section('c')]));

            h.mutation.onSectionDrop(dropEvent(section('b'), 1));

            expect(h.ctx.sections.map(s => s.name)).toEqual(['a', 'b', 'c']);
            expect(h.ctx.newSections.map((s: any) => s.name)).toEqual(['b']);
        });


        it('appends when the drop carries no index', () => {
            const h = harness(seeded([section('a')]));

            h.mutation.onSectionDrop(dropEvent(section('b'), undefined));

            expect(h.ctx.sections.map(s => s.name)).toEqual(['a', 'b']);
        });


        it('appends to an empty canvas', () => {
            const h = harness();

            h.mutation.onSectionDrop(dropEvent(section('first'), undefined));

            expect(h.ctx.sections.map(s => s.name)).toEqual(['first']);
            expect(h.ctx.typeInstance.render_meta.sections.map((s: any) => s.name)).toEqual(['first']);
        });


        it('ignores a cancelled drag (dropEffect "none")', () => {
            const h = harness(seeded([section('a')]));

            h.mutation.onSectionDrop(dropEvent(section('b'), 0, 'none'));

            expect(h.ctx.sections.map(s => s.name)).toEqual(['a']);
            expect(h.ctx.newSections.length).toBe(0);
        });


        it('registers the new identifier with the section registry at the drop index', () => {
            const h = harness(seeded([section('a')]));

            h.mutation.onSectionDrop(dropEvent(section('b'), 1));

            expect(h.deps.sectionIdentifierService.addSection).toHaveBeenCalledWith('b', 'b', 1);
            expect(h.deps.sectionIdentifierService.syncSections).toHaveBeenCalledWith(['a', 'b']);
        });


        it('reports the dropped section as invalid until it has fields', () => {
            const h = harness();

            h.mutation.onSectionDrop(dropEvent(section('a'), 0));

            expect(h.validationService.setSectionValid).toHaveBeenCalledWith('a', false);
        });


        /**
         * `writeSections` must assign a **fresh** array: the canvas `ngDoCheck` and the wizard steps'
         * `KeyValueDiffer` both detect replacement, not mutation. A section dropped into an array that
         * was only mutated in place would never reach the wizard's validity check.
         */
        it('publishes a fresh model array and keeps the change-detection reference on it', () => {
            const h = harness(seeded([section('a')]));
            const before = h.ctx.typeInstance.render_meta.sections;

            h.mutation.onSectionDrop(dropEvent(section('b'), 1));

            expect(h.ctx.typeInstance.render_meta.sections).not.toBe(before);
            expect(h.ctx.sectionReference).toBe(h.ctx.typeInstance.render_meta.sections);
        });


        it('auto-creates the companion selection field for a ref-section', () => {
            const h = harness();

            h.mutation.onSectionDrop(dropEvent(section('refs', { type: 'ref-section' }), 0));

            expect(h.ctx.sections[0].fields).toEqual(['refs-field']);
            expect(h.ctx.typeInstance.fields.map((f: any) => f.name)).toEqual(['refs-field']);
            expect(h.ctx.typeInstance.fields[0].type).toBe('ref-section-field');
        });


        it('does not create a companion field when a ref-section is only being moved', () => {
            const refSection = section('refs', { type: 'ref-section', fields: ['refs-field'] });
            const h = harness(seeded([refSection, section('b')]));
            h.ctx.typeInstance.fields = [field('refs-field', { type: 'ref-section-field' })];

            h.mutation.onDragStart(0);
            h.mutation.onSectionDrop(dropEvent(refSection, 2, 'move'));
            h.mutation.onSectionMoved(refSection, 'move');

            expect(h.ctx.typeInstance.fields.filter((f: any) => f.name === 'refs-field').length).toBe(1);
        });
    });

    /* ================================================================================================================ */
    /*                                   SECTION REORDER - THE TWO-PHASE PROTOCOL                                       */
    /* ================================================================================================================ */

    describe('reordering a section (two-phase)', () => {

        function threeSections(): Harness {
            const h = harness(seeded([section('a'), section('b'), section('c')]));
            return h;
        }

        /**
         * Phase one. The drop must only *record* where the section landed. If it spliced here as well
         * as in `dndMoved`, the section would exist twice - which is exactly the bug the deleted
         * relation canvas shipped.
         */
        it('records a pending index on drop without touching the list', () => {
            const h = threeSections();
            h.mutation.onDragStart(0);

            h.mutation.onSectionDrop(dropEvent(h.ctx.sections[0], 2, 'move'));

            expect(h.ctx.pendingSectionDropIndex).toBe(2);
            expect(h.ctx.sections.map(s => s.name)).toEqual(['a', 'b', 'c']);
            expect(h.ctx.newSections.length).withContext('a move is not a new section').toBe(0);
        });


        it('performs the move on the move event, leaving exactly one copy', () => {
            const h = threeSections();
            const moved = h.ctx.sections[0];

            h.mutation.onDragStart(0);
            h.mutation.onSectionDrop(dropEvent(moved, 2, 'move'));
            h.mutation.onSectionMoved(moved, 'move');

            expect(h.ctx.sections.map(s => s.name)).toEqual(['b', 'c', 'a']);
            expect(h.ctx.sections.filter(s => s.name === 'a').length).toBe(1);
        });


        it('moves the last section to the front', () => {
            const h = threeSections();
            const moved = h.ctx.sections[2];

            h.mutation.onDragStart(2);
            h.mutation.onSectionDrop(dropEvent(moved, 0, 'move'));
            h.mutation.onSectionMoved(moved, 'move');

            expect(h.ctx.sections.map(s => s.name)).toEqual(['c', 'a', 'b']);
        });


        it('leaves the order unchanged when a section is dropped on itself', () => {
            const h = threeSections();
            const moved = h.ctx.sections[1];

            h.mutation.onDragStart(1);
            h.mutation.onSectionDrop(dropEvent(moved, 1, 'move'));
            h.mutation.onSectionMoved(moved, 'move');

            expect(h.ctx.sections.map(s => s.name)).toEqual(['a', 'b', 'c']);
        });


        it('clamps a drop index past the end to the last position', () => {
            const h = threeSections();
            const moved = h.ctx.sections[0];

            h.mutation.onDragStart(0);
            h.mutation.onSectionDrop(dropEvent(moved, 99, 'move'));
            h.mutation.onSectionMoved(moved, 'move');

            expect(h.ctx.sections.map(s => s.name)).toEqual(['b', 'c', 'a']);
        });


        /**
         * A move event with no preceding drop means the drag was released outside the zone. The order
         * is asserted, but so is the *absence* of a re-sync: a move that silently ran and happened to
         * land the section back where it started would still pass an order-only check.
         */
        it('ignores a move event with no pending drop', () => {
            const h = threeSections();
            h.deps.sectionIdentifierService.syncSections.calls.reset();

            h.mutation.onSectionMoved(h.ctx.sections[0], 'move');

            expect(h.ctx.sections.map(s => s.name)).toEqual(['a', 'b', 'c']);
            expect(h.ctx.pendingSectionDropIndex).toBeNull();
            expect(h.deps.sectionIdentifierService.syncSections)
                .withContext('no move may be attempted at all')
                .not.toHaveBeenCalled();
        });


        it('ignores a non-move effect and clears the pending index', () => {
            const h = threeSections();
            h.mutation.onDragStart(0);
            h.mutation.onSectionDrop(dropEvent(h.ctx.sections[0], 2, 'move'));

            h.mutation.onSectionMoved(h.ctx.sections[0], 'copy' as any);

            expect(h.ctx.sections.map(s => s.name)).toEqual(['a', 'b', 'c']);
            expect(h.ctx.pendingSectionDropIndex).toBeNull();
            expect(h.ctx.draggedSectionIndex).toBeNull();
        });


        it('refuses to move a schema-locked section', () => {
            const h = harness({ ...seeded([section('locked'), section('b')]), lockedSectionNames: ['locked'] });
            const locked = h.ctx.sections[0];

            h.mutation.onDragStart(0);
            h.mutation.onSectionDrop(dropEvent(locked, 1, 'move'));
            h.mutation.onSectionMoved(locked, 'move');

            expect(h.ctx.sections.map(s => s.name)).toEqual(['locked', 'b']);
        });


        it('refuses to move a system (dg_gst-) section', () => {
            const h = harness(seeded([section('dg_gst-x'), section('b')]));
            const system = h.ctx.sections[0];

            h.mutation.onDragStart(0);
            h.mutation.onSectionDrop(dropEvent(system, 1, 'move'));
            h.mutation.onSectionMoved(system, 'move');

            expect(h.ctx.sections.map(s => s.name)).toEqual(['dg_gst-x', 'b']);
        });


        /** A global-template section is locked for editing but stays movable on purpose. */
        it('still allows an applied global-template section to be reordered', () => {
            const applied = { name: 'gt', label: 'GT', public_id: 2, fields: [] };
            const h = harness({
                ...seeded([section('gt'), section('b')]),
                selectedGlobalSectionTemplates: [applied]
            });
            const globalSection = h.ctx.sections[0];

            h.mutation.onDragStart(0);
            h.mutation.onSectionDrop(dropEvent(globalSection, 1, 'move'));
            h.mutation.onSectionMoved(globalSection, 'move');

            expect(h.ctx.sections.map(s => s.name)).toEqual(['b', 'gt']);
        });


        it('resets the drag bookkeeping when a new drag starts', () => {
            const h = threeSections();
            h.ctx.activeIndex = 2;
            h.ctx.pendingSectionDropIndex = 1;

            h.mutation.onDragStart(0);

            expect(h.ctx.draggedSectionIndex).toBe(0);
            expect(h.ctx.activeIndex).toBeNull();
            expect(h.ctx.pendingSectionDropIndex).toBeNull();
        });


        it('falls back to the section\'s current position when no drag index was recorded', () => {
            const h = threeSections();
            const moved = h.ctx.sections[2];
            h.ctx.pendingSectionDropIndex = 0;

            h.mutation.onSectionMoved(moved, 'move');

            expect(h.ctx.sections.map(s => s.name)).toEqual(['c', 'a', 'b']);
        });


        it('re-syncs the identifier registry with the new order', () => {
            const h = threeSections();
            const moved = h.ctx.sections[0];

            h.mutation.onDragStart(0);
            h.mutation.onSectionDrop(dropEvent(moved, 2, 'move'));
            h.deps.sectionIdentifierService.syncSections.calls.reset();
            h.mutation.onSectionMoved(moved, 'move');

            expect(h.deps.sectionIdentifierService.syncSections).toHaveBeenCalledWith(['b', 'c', 'a']);
        });
    });

    /* ================================================================================================================ */
    /*                                                   FIELD DROP                                                     */
    /* ================================================================================================================ */

    describe('dropping a field', () => {

        it('inserts a new field at the drop index', () => {
            const target = section('s', { fields: [field('a'), field('c')] });
            const h = harness(seeded([target]));

            h.mutation.onFieldDrop(dropEvent(field('b'), 1), target);

            expect(target.fields.map((f: any) => f.name)).toEqual(['a', 'b', 'c']);
            expect(h.ctx.typeInstance.fields.map((f: any) => f.name)).toContain('b');
        });


        it('appends when the drop carries no index', () => {
            const target = section('s', { fields: [field('a')] });
            const h = harness(seeded([target]));

            h.mutation.onFieldDrop(dropEvent(field('b'), undefined), target);

            expect(target.fields.map((f: any) => f.name)).toEqual(['a', 'b']);
        });


        it('ignores a cancelled drag (dropEffect "none")', () => {
            const target = section('s', { fields: [] });
            const h = harness(seeded([target]));

            h.mutation.onFieldDrop(dropEvent(field('a'), 0, 'none'), target);

            expect(target.fields.length).toBe(0);
            expect(h.ctx.typeInstance.fields.length).toBe(0);
        });


        it('marks the section valid once it holds a field', () => {
            const target = section('s', { fields: [] });
            const h = harness(seeded([target]));

            h.mutation.onFieldDrop(dropEvent(field('a'), 0), target);

            expect(h.validationService.setSectionValid).toHaveBeenCalledWith('s', true);
        });


        it('publishes a fresh flat field array', () => {
            const target = section('s', { fields: [] });
            const h = harness(seeded([target]));
            const before = h.ctx.typeInstance.fields;

            h.mutation.onFieldDrop(dropEvent(field('a'), 0), target);

            expect(h.ctx.typeInstance.fields).not.toBe(before);
        });


        it('rejects a drop into an applied global-template section', () => {
            const applied = { name: 'gt', label: 'GT', public_id: 2, fields: [] };
            const target = section('gt', { fields: [] });
            const h = harness({ ...seeded([target]), selectedGlobalSectionTemplates: [applied] });

            h.mutation.onFieldDrop(dropEvent(field('a'), 0), target);

            expect(target.fields.length).toBe(0);
            expect(h.ctx.typeInstance.fields.length).toBe(0);
        });


        it('rejects a drop into a schema-locked section', () => {
            const target = section('locked', { fields: [] });
            const h = harness({ ...seeded([target]), lockedSectionNames: ['locked'] });

            h.mutation.onFieldDrop(dropEvent(field('a'), 0), target);

            expect(target.fields.length).toBe(0);
        });


        /**
         * The Location control must never live inside a multi-data-section. The palette's dnd types
         * already stop it being dragged there from the sidebar, but a location field can be dragged
         * *out of a normal section*, so the drop itself is the authoritative choke point. Both guards
         * are deliberate; this covers the second one.
         */
        describe('location cannot enter a multi-data-section', () => {

            it('rejects a location field dropped into a multi-data-section', () => {
                const mds = section('mds', { type: 'multi-data-section', fields: [] });
                const h = harness(seeded([mds]));

                h.mutation.onFieldDrop(dropEvent(field('dg_location', { type: 'location' }), 0), mds);

                expect(mds.fields.length).toBe(0);
            });


            it('rejects a location field dragged out of a normal section into a multi-data-section', () => {
                const normal = section('normal', { fields: [field('dg_location', { type: 'location' })] });
                const mds = section('mds', { type: 'multi-data-section', fields: [] });
                const h = harness(seeded([normal, mds]));
                const location = normal.fields[0];

                h.mutation.onFieldDragStart(location, normal, 0);
                h.mutation.onFieldDrop(dropEvent(location, 0, 'move'), mds);

                expect(mds.fields.length).toBe(0);
                expect(normal.fields.map((f: any) => f.name))
                    .withContext('the field must stay where it was')
                    .toEqual(['dg_location']);
            });


            it('accepts a location field into a normal section', () => {
                const target = section('s', { fields: [] });
                const h = harness(seeded([target]));

                h.mutation.onFieldDrop(dropEvent(field('dg_location', { type: 'location' }), 0), target);

                expect(target.fields.map((f: any) => f.name)).toEqual(['dg_location']);
            });


            it('accepts a regular field into a multi-data-section', () => {
                const mds = section('mds', { type: 'multi-data-section', fields: [] });
                const h = harness(seeded([mds]));

                h.mutation.onFieldDrop(dropEvent(field('a'), 0), mds);

                expect(mds.fields.map((f: any) => f.name)).toEqual(['a']);
            });
        });
    });

    /* ================================================================================================================ */
    /*                                                  FIELD MOVING                                                    */
    /* ================================================================================================================ */

    describe('moving a field', () => {

        it('relocates a field to another section without duplicating it', () => {
            const from = section('from', { fields: [field('a'), field('b')] });
            const to = section('to', { fields: [field('c')] });
            const h = harness(seeded([from, to]));
            const moved = from.fields[0];

            h.mutation.onFieldDragStart(moved, from, 0);
            h.mutation.onFieldDrop(dropEvent(moved, 1, 'move'), to);

            expect(from.fields.map((f: any) => f.name)).toEqual(['b']);
            expect(to.fields.map((f: any) => f.name)).toEqual(['c', 'a']);
            expect(h.ctx.typeInstance.fields.filter((f: any) => f.name === 'a').length)
                .withContext('the flat field list must not gain a copy')
                .toBe(1);
        });


        it('appends to the target section when the move carries no index', () => {
            const from = section('from', { fields: [field('a')] });
            const to = section('to', { fields: [field('c')] });
            const h = harness(seeded([from, to]));
            const moved = from.fields[0];

            h.mutation.onFieldDragStart(moved, from, 0);
            h.mutation.onFieldDrop(dropEvent(moved, undefined, 'move'), to);

            expect(to.fields.map((f: any) => f.name)).toEqual(['c', 'a']);
        });


        /**
         * Moving a field *forward* inside its own section needs the target index decremented, because
         * the field is spliced out before it is spliced back in. The drop index counts slots in the
         * list the user is still looking at, which still contains the field being dragged.
         *
         * This has to land in the *middle* of the list to mean anything: dropping at the very end
         * gives the same answer either way, because splicing past the end just appends.
         */
        it('reorders forward within the same section', () => {
            const only = section('s', { fields: [field('a'), field('b'), field('c'), field('d')] });
            const h = harness(seeded([only]));
            const moved = only.fields[0];

            // Dropped between "b" and "c" as the user sees them.
            h.mutation.onFieldDragStart(moved, only, 0);
            h.mutation.onFieldDrop(dropEvent(moved, 2, 'move'), only);

            expect(only.fields.map((f: any) => f.name)).toEqual(['b', 'a', 'c', 'd']);
        });


        it('reorders to the very end of its own section', () => {
            const only = section('s', { fields: [field('a'), field('b'), field('c')] });
            const h = harness(seeded([only]));
            const moved = only.fields[0];

            h.mutation.onFieldDragStart(moved, only, 0);
            h.mutation.onFieldDrop(dropEvent(moved, 3, 'move'), only);

            expect(only.fields.map((f: any) => f.name)).toEqual(['b', 'c', 'a']);
        });


        it('reorders backward within the same section', () => {
            const only = section('s', { fields: [field('a'), field('b'), field('c')] });
            const h = harness(seeded([only]));
            const moved = only.fields[2];

            h.mutation.onFieldDragStart(moved, only, 2);
            h.mutation.onFieldDrop(dropEvent(moved, 0, 'move'), only);

            expect(only.fields.map((f: any) => f.name)).toEqual(['c', 'a', 'b']);
        });


        it('keeps exactly one copy when a field is dropped back where it started', () => {
            const only = section('s', { fields: [field('a'), field('b')] });
            const h = harness(seeded([only]));
            const moved = only.fields[0];

            h.mutation.onFieldDragStart(moved, only, 0);
            h.mutation.onFieldDrop(dropEvent(moved, 0, 'move'), only);

            expect(only.fields.map((f: any) => f.name)).toEqual(['a', 'b']);
        });


        /** `dndStart` may not have fired (or may be stale); the source section is then searched for. */
        it('finds the source section when no drag was recorded', () => {
            const from = section('from', { fields: [field('a')] });
            const to = section('to', { fields: [] });
            const h = harness(seeded([from, to]));

            h.mutation.onFieldDrop(dropEvent(from.fields[0], 0, 'move'), to);

            expect(from.fields.length).toBe(0);
            expect(to.fields.map((f: any) => f.name)).toEqual(['a']);
        });


        it('refuses to move a field out of a locked section', () => {
            const from = section('locked', { fields: [field('a')] });
            const to = section('to', { fields: [] });
            const h = harness({ ...seeded([from, to]), lockedSectionNames: ['locked'] });
            const moved = from.fields[0];

            h.mutation.onFieldDragStart(moved, from, 0);
            h.mutation.onFieldDrop(dropEvent(moved, 0, 'move'), to);

            expect(from.fields.map((f: any) => f.name)).toEqual(['a']);
            expect(to.fields.length).toBe(0);
        });


        /** An existing field is recognised by name, not only by object identity. */
        it('treats a field carrying a known name as a move, not a new field', () => {
            const from = section('from', { fields: [field('a')] });
            const to = section('to', { fields: [] });
            const h = harness(seeded([from, to]));

            h.mutation.onFieldDrop(dropEvent({ ...from.fields[0] }, 0, 'move'), to);

            expect(h.ctx.typeInstance.fields.filter((f: any) => f.name === 'a').length).toBe(1);
            expect(h.ctx.newFields.length).withContext('a move must not register a new field').toBe(0);
        });


        it('clears the recorded drag once the move completes', () => {
            const from = section('from', { fields: [field('a')] });
            const to = section('to', { fields: [] });
            const h = harness(seeded([from, to]));
            const moved = from.fields[0];

            h.mutation.onFieldDragStart(moved, from, 0);
            h.mutation.onFieldDrop(dropEvent(moved, 0, 'move'), to);

            expect(h.ctx.draggedField).toBeNull();
        });


        it('keeps the moved field valid in the target section', () => {
            const from = section('from', { fields: [field('a')] });
            const to = section('to', { fields: [] });
            const h = harness(seeded([from, to]));
            const moved = from.fields[0];

            h.mutation.onFieldDragStart(moved, from, 0);
            h.mutation.onFieldDrop(dropEvent(moved, 0, 'move'), to);

            expect(h.validationService.setSectionValid).toHaveBeenCalledWith('to', true);
        });


        it('republishes the section projection so the canvas re-renders both sections', () => {
            const from = section('from', { fields: [field('a')] });
            const to = section('to', { fields: [] });
            const h = harness(seeded([from, to]));
            const before = h.ctx.typeInstance.render_meta.sections;
            const moved = from.fields[0];

            h.mutation.onFieldDragStart(moved, from, 0);
            h.mutation.onFieldDrop(dropEvent(moved, 0, 'move'), to);

            expect(h.ctx.typeInstance.render_meta.sections).not.toBe(before);
        });
    });
});
