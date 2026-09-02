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
import { BuilderSection } from '../schema/builder-section.model';
import { BuilderInteractionPolicy, BuilderInteractionPolicyContext } from './builder-interaction-policy';
import { BuilderUtils } from './builder-utils';
/* ------------------------------------------------------------------------------------------------------------------ */

/**
 * The section card's icons must keep their reference between checks.
 *
 * `<fa-icon [icon]>` is a signal input. A helper that answers with a fresh `['fas', 'object-group']`
 * every time is therefore reporting a *new value* on every change detection run: the icon's rendered
 * HTML is recomputed, the view is marked dirty, another run is scheduled, and that run calls the
 * helper again. The section template builder runs on default change detection, so nothing damps
 * that cycle - the tab spins at 100% CPU and stops responding (DAT-3058).
 *
 * Equality is not enough to pin this down; identity is the contract.
 */
describe('Builder section icons', () => {

    const emptyContext = (): BuilderInteractionPolicyContext => ({
        selectedGlobalSectionTemplates: [],
        globalTemplateIds: [],
        globalFieldNames: [],
        schemaLockedSectionNames: [],
        schemaLockedFieldNames: []
    });

    const section = (overrides: Partial<BuilderSection> = {}): BuilderSection => ({
        name: 'section-1',
        label: 'Section',
        type: 'section',
        fields: [],
        ...overrides
    } as BuilderSection);


    it('answers with the same reference for a repeated section type', () => {
        expect(BuilderUtils.matchedSectionType('section'))
            .toBe(BuilderUtils.matchedSectionType('section'));
        expect(BuilderUtils.matchedSectionType('multi-data-section'))
            .toBe(BuilderUtils.matchedSectionType('multi-data-section'));
        expect(BuilderUtils.matchedSectionType('ref-section'))
            .toBe(BuilderUtils.matchedSectionType('ref-section'));
    });


    it('still distinguishes the section types', () => {
        expect(BuilderUtils.matchedSectionType('section')).toEqual(['fas', 'object-group']);
        expect(BuilderUtils.matchedSectionType('multi-data-section')).toEqual(['fas', 'list-ol']);
        expect(BuilderUtils.matchedSectionType('ref-section')).toEqual(['fas', 'layer-group']);
        expect(BuilderUtils.matchedSectionType('anything-else')).toEqual(['fas', 'object-group']);
    });


    it('answers with the same collapse icon reference for a repeated section', () => {
        const policy = new BuilderInteractionPolicy(emptyContext);
        const editable = section();
        const readOnly = section({ name: 'dg_gst-locked' });

        expect(policy.getSectionCollapseIcon(editable)).toBe(policy.getSectionCollapseIcon(editable));
        expect(policy.getSectionCollapseIcon(readOnly)).toBe(policy.getSectionCollapseIcon(readOnly));

        expect(policy.getSectionCollapseIcon(editable)).toEqual(['far', 'edit']);
        expect(policy.getSectionCollapseIcon(readOnly)).toEqual(['far', 'eye']);
    });
});
