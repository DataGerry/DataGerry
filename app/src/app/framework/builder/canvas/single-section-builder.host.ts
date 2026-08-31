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
import { ValidationService } from '../services/validation.service';
import { BuilderSection } from '../schema/builder-section.model';
import { BuilderUtils } from '../utils/builder-utils';
import { BuilderSectionHost } from './builder-section-host';
/* ------------------------------------------------------------------------------------------------------------------ */

/**
 * Hosts a single, fixed section - the section template builder's whole canvas.
 *
 * There is no section list, so nothing can be reordered, removed or locked and the section header
 * carries no actions. The section itself is read through a provider because the page swaps the whole
 * object when it renames the template, which is how the bound editor's form follows the change.
 */
export class SingleSectionBuilderHost implements BuilderSectionHost {

    public readonly types: Array<CmdbType> = [];
    public readonly disableFields = false;
    public readonly showSectionActions = false;
    public readonly staticSectionEditor = true;

    /** Stable references so the bindings that consume them do not churn on every check. */
    private readonly noExternalLinks = { links: [] as Array<any>, total: 0 };
    private readonly headerClass: Record<string, boolean> = {};
    private sectionsView: Array<BuilderSection> = [];

    constructor(
        private readonly sectionProvider: () => BuilderSection,
        private readonly validationService: ValidationService
    ) {}


    public get section(): BuilderSection {
        return this.sectionProvider();
    }


    public get sections(): Array<BuilderSection> {
        const section = this.section;

        if (this.sectionsView[0] !== section) {
            this.sectionsView = section ? [section] : [];
        }

        return this.sectionsView;
    }


    public get fields(): Array<any> {
        return this.section?.fields ?? [];
    }

    /* ------------------------------------------------ PRESENTATION ---------------------------------------------------- */

    public getSectionMode(): CmdbMode {
        // The template's own identifier is generated, never typed, so the editor stays in Edit mode.
        return CmdbMode.Edit;
    }

    public getFieldMode(): CmdbMode {
        return CmdbMode.Edit;
    }

    public getSectionCollapseIcon(): [string, string] {
        return ['far', 'edit'];
    }

    public getSectionHeaderClass(): Record<string, boolean> {
        return this.headerClass;
    }

    public getFieldDropTypes(): Array<string> {
        return ['inputs'];
    }

    /**
     * Always a plain section, even when the template itself is a multi-data-section.
     *
     * A section template has no `hidden_fields`: this page serialises `initialSection.fields`
     * straight to the backend, and nothing here routes a `hideField` change anywhere. Reporting the
     * real type would render the MDS "hide this field as column" checkbox, and ticking it would
     * write a stray `hideField` flag onto the field and save it. The old page bound no
     * `fieldSectionType` at all, so the control never appeared.
     */
    public getFieldSectionType(): string {
        return 'section';
    }


    public getFieldDragEffect(): string {
        return 'move';
    }

    public getFieldHiddenState(): boolean {
        return false;
    }

    public matchedType(fieldType: string): string {
        return BuilderUtils.matchedType(fieldType);
    }

    /* ------------------------------------------------- PERMISSIONS ---------------------------------------------------- */

    public canMoveSection(): boolean {
        return false;
    }

    public canRemoveSection(): boolean {
        return false;
    }

    public canDropFieldsIntoSection(): boolean {
        return true;
    }

    public canMoveField(): boolean {
        return true;
    }

    public canRemoveField(): boolean {
        return true;
    }

    public isLockedField(): boolean {
        return false;
    }

    public isFieldHighlighted(): boolean {
        return false;
    }

    public isAnySectionHighlighted(): boolean {
        return false;
    }

    public isLocked(): boolean {
        return false;
    }

    public isFieldEditDisabled(): boolean {
        return false;
    }

    public externalField(): { links: Array<any>; total: number } {
        return this.noExternalLinks;
    }

    /* ---------------------------------------------------- EVENTS ------------------------------------------------------ */

    public onSectionFocus(): void {
        // A single section is always the active one.
    }

    public onSectionDragStart(event: DragEvent): void {
        event?.stopPropagation();
        event?.preventDefault();
    }

    public onSectionRemove(): void {
        // The section is fixed; its header carries no remove button.
    }

    public onFieldDragBlocked(): void {
        // Nothing can lock the fields of a single section.
    }


    public onFieldDrop(event: DndDropEvent, section: BuilderSection): void {
        if (event?.dropEffect !== 'copy' && event?.dropEffect !== 'move') {
            return;
        }

        const fields = section?.fields;
        if (!fields) {
            return;
        }

        const dropped = event?.data;
        const targetIndex = event?.index ?? fields.length;
        const sourceIndex = this.indexOfDraggedField(fields, dropped);

        if (sourceIndex < 0) {
            fields.splice(targetIndex, 0, dropped);
            return;
        }

        // Reorder: take the field out first so the target index still refers to the intended slot,
        // and put the ORIGINAL entry back rather than the payload copy.
        const [moved] = fields.splice(sourceIndex, 1);
        fields.splice(targetIndex > sourceIndex ? targetIndex - 1 : targetIndex, 0, moved);
    }


    /**
     * Where the dropped payload already lives in this section, or -1 if it is a new field.
     *
     * ngx-drag-drop puts the payload through `JSON.stringify`/`JSON.parse`, so what a drop hands back
     * is **never** the array entry that was dragged. Matching on object identity therefore always
     * misses, and the reorder silently becomes an insert - i.e. the field gets duplicated. The
     * identifier is the only thing that survives the round trip, which is what the canvas' own
     * `isExistingField` matches on too.
     */
    private indexOfDraggedField(fields: Array<any>, dropped: any): number {
        if (!dropped?.name) {
            return -1;
        }

        return fields.findIndex(field => field === dropped || field?.name === dropped.name);
    }


    public onFieldDragStart(): void {
        // The drop handler resolves a reorder from the payload's identifier.
    }


    public onFieldRemove(field: any, section: BuilderSection): void {
        const fields = section?.fields ?? [];
        const index = fields.indexOf(field);

        if (index < 0) {
            return;
        }

        const removedFieldName = fields[index]?.name;
        fields.splice(index, 1);
        this.validationService?.updateFieldValidityOnDeletion(removedFieldName);
    }


    public onValuesChanged(data: any): void {
        if (!data || data.hasOwnProperty('isDuplicate')) {
            return;
        }

        const section = this.section;
        if (!section) {
            return;
        }

        if (data.elementType === 'section' || data.elementType === 'multi-data-section') {
            section[data.inputName] = data.newValue;
            return;
        }

        // `hidden_fields` is a type-level concept. This page has nowhere to put it, and its fields
        // are serialised verbatim into the saved template, so storing the flag would ship a stray
        // property to the backend. The control is not offered here (see getFieldSectionType); this
        // guard keeps that true no matter where the event came from.
        if (data.inputName === 'hideField') {
            return;
        }

        const index = (section.fields ?? []).findIndex(field => field?.name === data.fieldName);

        if (index >= 0) {
            section.fields[index][data.inputName] = data.newValue;
        }
    }
}
