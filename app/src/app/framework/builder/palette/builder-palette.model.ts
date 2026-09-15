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
* along with this program.  If not, see <https://www.gnu.org/licenses/>.
*/
import { ControlsCommon } from '../controls/controls.common';
import { SectionTemplateListItem } from '../../section_templates/models/virtual-section-template.model';
/* ------------------------------------------------------------------------------------------------------------------ */

/**
 * How a group stops its items being dragged while the canvas has unresolved errors.
 *
 * The type builder uses `dndDisableIf` for the template and basic-control groups but the raw
 * `draggable` attribute for the structure and special groups. The split is deliberate - a
 * draggable disabled mid-drag loses its dragend cleanup and leaves a stuck placeholder - so it
 * is carried per group rather than unified.
 */
export type BuilderPaletteLockMode = 'dnd-disable' | 'draggable-attr';

export interface BuilderPaletteItem {
    label: string;

    /** Font Awesome class string, e.g. 'fas fa-font'. Absent for section templates. */
    icon?: string;

    /** Leading identifier shown before the label, e.g. '#12' for a section template. */
    badge?: string;

    /** Emphasises the label, marking the item as a section template rather than a control. */
    strong?: boolean;

    /** ngx-drag-drop type this item drops into: 'sections', 'inputs' or 'location'. */
    dndType: string;

    /** Fresh drop payload. Called per change detection, matching the previous inline binding. */
    payload: () => unknown;
}

export interface BuilderPaletteGroup {
    /** Bootstrap collapse target id. Must stay stable - it is a document-level selector. */
    id: string;
    label: string;
    items: ReadonlyArray<BuilderPaletteItem>;

    /** Only the first expanded group should be open, matching `collapse show`. */
    expanded?: boolean;

    lockMode?: BuilderPaletteLockMode;
}

/** Maps builder controls onto palette items. */
export function paletteItemsFromControls(controls: ReadonlyArray<ControlsCommon>): Array<BuilderPaletteItem> {
    return controls.map(control => ({
        label: control.label,
        icon: control.icon,
        dndType: control.dndType,
        payload: () => control.content()
    }));
}

/**
 * Maps section templates onto palette items; they drop as sections and carry no icon.
 * A virtual template has no public_id, so it is listed by its label alone.
 */
export function paletteItemsFromSectionTemplates(
    templates: ReadonlyArray<SectionTemplateListItem>
): Array<BuilderPaletteItem> {
    return templates.map(template => ({
        label: template?.label,
        badge: template?.public_id ? `#${template.public_id}` : undefined,
        strong: true,
        dndType: 'sections',
        payload: () => template
    }));
}
