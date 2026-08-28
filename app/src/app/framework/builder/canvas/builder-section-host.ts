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
import { DndDropEvent } from 'ngx-drag-drop';

import { CmdbType } from '../../models/cmdb-type';
import { CmdbMode } from '../../modes.enum';
import { BuilderSection } from '../schema/builder-section.model';
/* ------------------------------------------------------------------------------------------------------------------ */

/**
 * Everything `<dg-builder-section>` needs from whoever owns the section.
 *
 * The canvas implements it over the full permission / highlight / mutation machinery; the section
 * template page implements it over a single fixed section. Keeping it an interface is what lets one
 * section card serve both without the card itself knowing which builder it is in.
 */
export interface BuilderSectionHost {

    /** Every section the host is showing - the section editors use it to spot duplicate identifiers. */
    readonly sections: Array<BuilderSection>;

    /** The model's flat field list. */
    readonly fields: Array<any>;

    readonly types: Array<CmdbType>;

    /** True while a duplicate identifier has the builder latched. */
    readonly disableFields: boolean;

    /** A fixed single section has no collapse, move or remove buttons. */
    readonly showSectionActions: boolean;

    /**
     * Binds the section editor statically instead of through `cmdb-config-edit`.
     *
     * `SectionFieldEditComponent.ngOnChanges` never fires on the dynamic dispatcher path - it assigns
     * `instance.data` once - so a host that renames its section through the model needs a real
     * template binding for the form to follow along.
     */
    readonly staticSectionEditor: boolean;

    getSectionMode(section: BuilderSection): CmdbMode;
    getFieldMode(field: any): CmdbMode;
    getSectionCollapseIcon(section: BuilderSection): [string, string];
    getSectionHeaderClass(section: BuilderSection): Record<string, boolean>;

    /** ngx-drag-drop types the section's field zone accepts. */
    getFieldDropTypes(section: BuilderSection): Array<string>;
    getFieldDragEffect(field: any): string;
    getFieldHiddenState(section: BuilderSection, field: any): boolean;

    canMoveSection(section: BuilderSection): boolean;
    canRemoveSection(section: BuilderSection): boolean;
    canDropFieldsIntoSection(section: BuilderSection): boolean;
    canMoveField(field: any): boolean;
    canRemoveField(field: any): boolean;
    isLockedField(field: any): boolean;
    isFieldHighlighted(field: any, section: BuilderSection): boolean;
    isAnySectionHighlighted(): boolean;

    /** True while an unnamed field locks every other interaction. */
    isLocked(): boolean;

    /** True when this field's config editor must be greyed out. */
    isFieldEditDisabled(sectionIndex: number, fieldIndex: number): boolean;

    /** External links referencing the field, so its remove button can explain why it is blocked. */
    externalField(field: any): { links: Array<any>; total: number };

    matchedType(fieldType: string): string;

    onSectionFocus(index: number): void;
    onSectionDragStart(event: DragEvent, section: BuilderSection): void;
    onSectionRemove(section: BuilderSection, index: number): void;

    onFieldDragBlocked(event: DragEvent, section: BuilderSection): void;
    onFieldDrop(event: DndDropEvent, section: BuilderSection): void;
    onFieldDragStart(field: any, section: BuilderSection, index: number): void;
    onFieldRemove(field: any, section: BuilderSection): void;

    /** Config-edit changes. Section edits arrive without indices, field edits with both. */
    onValuesChanged(data: any, sectionIndex?: number, fieldIndex?: number): void;
}
