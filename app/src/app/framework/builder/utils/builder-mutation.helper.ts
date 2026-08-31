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
import { ElementRef, Renderer2 } from '@angular/core';
import { DndDropEvent, DropEffect } from 'ngx-drag-drop';

import { CmdbMode } from '../../modes.enum';
import { ValidationService } from 'src/app/framework/builder/services/validation.service';
import { SectionIdentifierService } from 'src/app/framework/builder/services/SectionIdentifierService.service';
import { FieldIdentifierValidationService } from 'src/app/framework/builder/services/field-identifier-validation.service';
import { BuilderDeletionGuard } from '../services/builder-deletion-guard';
import { BuilderSection } from '../schema/builder-section.model';
import { BuilderUtils } from './builder-utils';
import { BuilderContext } from './builder-context';
import { BuilderInteractionPolicy } from './builder-interaction-policy';
import { BuilderHighlightHelper } from './builder-highlight.helper';
import { BuilderTemplateManager } from './builder-template.manager';

export interface BuilderMutationDeps {
    validationService: ValidationService;
    sectionIdentifierService: SectionIdentifierService;
    fieldIdentifierValidation: FieldIdentifierValidationService;
    /** Absent for builders with nothing to guard, e.g. relations. */
    deletionGuard: BuilderDeletionGuard | null;
    renderer: Renderer2;
    el: ElementRef;
}

/**
 * Owns the builder's model mutations: drag-and-drop of sections and fields, applying config-edit
 * changes back into the edited model, section/field removal and keeping the derived `sections`
 * projection in sync with it. All state flows through the shared BuilderContext, the model itself
 * is reached only through its schema adapter, and permission / highlight / template concerns are
 * delegated to their dedicated collaborators.
 */
export class BuilderMutationHelper {
    constructor(
        private readonly ctx: BuilderContext,
        private readonly deps: BuilderMutationDeps,
        private readonly policy: BuilderInteractionPolicy,
        private readonly highlight: BuilderHighlightHelper,
        private readonly templateManager: BuilderTemplateManager
    ) {}

    /* ------------------------------------------------ SYNCHRONISATION ------------------------------------------------ */

    public syncSectionsFromModel(): void {
        const preSectionList: Array<BuilderSection> = [];
        const modelFields = this.ctx.schema.readFields();

        for (const section of this.ctx.schema.readSections()) {
            const fieldBufferList = [];

            for (const field of section?.fields ?? []) {
                const fieldName = typeof field === 'string' ? field : field?.name;
                const found = modelFields?.find(modelField => modelField?.name === fieldName);

                if (found) {
                    fieldBufferList.push(found);
                }
            }

            preSectionList.push({
                ...section,
                fields: fieldBufferList
            });
        }

        this.ctx.sections = preSectionList;
        this.syncSectionIdentifiers();
    }

    public syncSectionIdentifiers(): void {
        const sectionNames = this.ctx.sections
            .map(section => section?.name)
            .filter(Boolean);

        this.deps.sectionIdentifierService.syncSections(sectionNames);
    }

    public refreshFieldIdentifiers(): void {
        BuilderUtils.refreshFieldIdentifiers(this.ctx.schema, this.deps.fieldIdentifierValidation);
    }

    private addRefSectionSelectionField(refSection: BuilderSection): void {
        refSection.fields = [];
        refSection?.fields?.push(`${refSection?.name}-field`);

        this.ctx.schema.readFields()?.push({
            type: 'ref-section-field',
            name: `${refSection?.name}-field`,
            label: refSection?.label
        });

        this.ctx.schema.writeFields(this.ctx.schema.readFields());
    }

    /**
     * The companion field is named after the section it was created for, so renaming the section
     * leaves the two out of step. The section's own `fields` entry still points at it, so that is
     * the handle to trust - and an unresolvable one means there is nothing to remove, never
     * `splice(-1, 1)`, which would drop whatever field happens to be last.
     */
    private removeRefSectionSelectionField(refSection: BuilderSection): void {
        const fields = this.ctx.schema.readFields();
        const companionName = this.refSectionCompanionName(refSection);
        const index = fields?.map(field => field?.name).indexOf(companionName) ?? -1;

        if (index < 0) {
            return;
        }

        fields.splice(index, 1);
        this.ctx.schema.writeFields(fields);
    }


    private refSectionCompanionName(refSection: BuilderSection): string {
        const tracked = (refSection?.fields ?? [])
            .map(field => typeof field === 'string' ? field : field?.name)
            .find(Boolean);

        return tracked ?? `${refSection?.name}-field`;
    }

    /* --------------------------------------------------- SECTION DND -------------------------------------------------- */

    public onDragStart(index: number): void {
        this.ctx.activeIndex = null
        this.ctx.draggedSectionIndex = index;
        this.ctx.pendingSectionDropIndex = null;
    }

    /**
     * Handels dropping any kind of section in the drop area
     *
     * @param event DropEvent containing the section as data
     */
    public onSectionDrop(event: DndDropEvent): void {

        event.event?.preventDefault();
        let sectionData = event?.data;

        //check if it is a section template
        if ('is_global' in sectionData) {

            if (sectionData.is_global) {
                this.ctx.selectedGlobalSectionTemplates?.push(sectionData);

                let index = 0;
                for (let sectionIndex in this.ctx.globalSectionTemplates) {
                    const aTemplate = this.ctx.globalSectionTemplates[sectionIndex];

                    if (aTemplate?.name == sectionData?.name) {
                        index = parseInt(sectionIndex);
                        break;
                    }
                }

                this.ctx.globalSectionTemplates?.splice(index, 1);
                this.ctx.schema.readGlobalTemplateIds()?.push(sectionData?.name);
            }

            sectionData = this.templateManager.extractSectionData(event?.data);
        }

        if (this.ctx.sections && (event?.dropEffect === 'copy' || event?.dropEffect === 'move')) {

            let index = event?.index;
            if (typeof index === 'undefined') {
                index = this.ctx.sections?.length;
            }

            for (const el of this.ctx.sections) {
                if (el.name && el?.name?.trim()) {
                    const collapseCard = this.deps.el?.nativeElement?.querySelector(`#${el?.name}`);
                    if (collapseCard) {
                        this.deps.renderer?.setStyle(collapseCard, 'display', 'none');
                    }
                }
            }

            if (event.dropEffect === 'move') {
                this.ctx.pendingSectionDropIndex = index;
                return;
            }

            if (event.dropEffect === 'copy') {
                this.ctx.newSections.push(sectionData);
            }

            this.ctx.sections.splice(index, 0, sectionData);
            this.commitSections();
            this.deps.sectionIdentifierService.getDroppedIndex(index);
            this.deps.sectionIdentifierService.addSection(sectionData?.name, sectionData?.name, index);
            this.syncSectionIdentifiers();

            if (sectionData?.type === 'ref-section' && event?.dropEffect === 'copy') {
                this.addRefSectionSelectionField(sectionData as BuilderSection);
            }

            //add fields of section template after the section was added
            if ('is_global' in event?.data) {
                this.templateManager.setSectionTemplateFields(event?.data);
            }
        }

        this.deps.validationService.setSectionValid(sectionData?.name, sectionData?.fields?.length > 0);
        this.highlight.updateSectionFieldStatus()
        this.highlight.updateHighlightState();
    }

    public onSectionMoved(item: BuilderSection, effect: DropEffect): void {
        if (effect !== 'move' || !this.policy.canMoveSection(item) || this.ctx.pendingSectionDropIndex === null) {
            this.clearPendingSectionMove();
            return;
        }

        const fallbackSourceIndex = this.ctx.sections.indexOf(item);
        const sourceIndex = this.ctx.draggedSectionIndex ?? fallbackSourceIndex;

        this.moveSection(sourceIndex, this.ctx.pendingSectionDropIndex);
        this.clearPendingSectionMove();
        this.highlight.updateSectionFieldStatus();
        this.highlight.updateHighlightState();
        this.refreshFieldIdentifiers();
    }

    /**
     * `targetIndex` is the placeholder's position among the rendered sections, and the dragged
     * section is still one of them. Dropping below its own slot therefore counts it once too often,
     * so the index has to shrink by one before the shortened list is spliced.
     */
    private moveSection(sourceIndex: number, targetIndex: number): void {
        if (sourceIndex < 0 || sourceIndex >= this.ctx.sections.length) {
            return;
        }

        const [movedSection] = this.ctx.sections.splice(sourceIndex, 1);
        const adjustedIndex = targetIndex > sourceIndex ? targetIndex - 1 : targetIndex;
        const nextIndex = Math.max(0, Math.min(adjustedIndex, this.ctx.sections.length));

        this.ctx.sections.splice(nextIndex, 0, movedSection);
        this.commitSections();
        this.syncSectionIdentifiers();
    }

    private clearPendingSectionMove(): void {
        this.ctx.draggedSectionIndex = null;
        this.ctx.pendingSectionDropIndex = null;
    }

    /**
     * Publishes the derived `sections` projection back onto the model as a fresh array and keeps the
     * canvas' change-detection reference pointing at it, so `ngDoCheck` does not resync needlessly.
     */
    private commitSections(): void {
        this.ctx.schema.writeSections(this.ctx.sections);
        this.ctx.sectionReference = this.ctx.schema.readSections();
    }

    /* ------------------------------------------------- EXTERNAL LINKS ------------------------------------------------- */

    /**
     * This method checks if the field is used for an external link.
     */
    public externalField(field) {
        const include = { links: [], total: 0 };

        for (const external of this.ctx.schema.readExternals()) {
            const fields = external?.hasOwnProperty('fields') ? Array.isArray(external?.fields) ? external?.fields : [] : [];
            const found = fields?.find(f => f === field?.name);

            if (found) {
                if (include?.total < 10) {
                    include?.links?.push(external);
                }

                include.total = include?.total + 1;
            }
        }

        return include;
    }

    /* -------------------------------------------------- FIELD CHANGES ------------------------------------------------- */

    /**
     * Redirects changes to field properties
     */
    public onFieldChange(data: any, sectionIndex?: number, fieldIndex?: number) {
        if (data.hasOwnProperty("isDuplicate")) {
            if (data?.isDuplicate) {
                this.ctx.activeDuplicateField = { sectionIndex, fieldIndex };
                this.setDisableFields(true);
            } else {
                this.ctx.activeDuplicateField = null;
                this.setDisableFields(false);
            }

            return;
        }

        this.ctx.activeDuplicateField = null;
        this.setDisableFields(false);
        this.handleFieldChanges(data);
    }

    private setDisableFields(value: boolean): void {
        if (this.ctx.disableFields === value) {
            return;
        }
        this.ctx.disableFields = value;
        this.deps.validationService?.setDisableFields(value);
    }

    /**
     * Sets and unsets a hidden field in the -ulti-data-ssection property 'hidden_fields'
     */
    private handleHideFields(data: any) {
        const sections = this.ctx.schema.readSections();
        let sectionIndex: number = this.getSectionOfField(data?.fieldName);
        let section: BuilderSection = sections[sectionIndex];

        if (!section) {
            return;
        }

        if (!("hidden_fields" in section)) {
            section.hidden_fields = [];
        }

        if (data.newValue == true) {
            section.hidden_fields.push(data?.fieldName);
        } else {
            section.hidden_fields = section.hidden_fields.filter(hiddenField => hiddenField != data?.fieldName);
        }

        sections[sectionIndex] = section;
    }

    /**
     * Updates the hidden_fields array of a section if the identifier was changed during the CREATE mode
     */
    private updateHiddenFields(previousName: string, newName: string) {
        const sections = this.ctx.schema.readSections();
        let sectionIndex: number = this.getSectionOfField(previousName);
        let section: BuilderSection = sections[sectionIndex];

        if (section?.hidden_fields?.includes(previousName)) {
            section.hidden_fields = section?.hidden_fields?.filter(hiddenField => hiddenField != previousName);
            section?.hidden_fields?.push(newName);
            sections[sectionIndex] = section;
        }
    }

    public getFieldHiddenState(section: BuilderSection, field: any): boolean {
        if (section.type == "multi-data-section") {
            if (section?.hidden_fields?.includes(field?.name)) {
                return true;
            } else {
                return false;
            }
        }

        return false;
    }

    /**
     * Sections hold field names at rest and resolved field objects once the builder has committed,
     * so both shapes have to be matched - a freshly loaded type reaches here as names.
     */
    private getSectionOfField(fieldName: string) {
        let index = 0;

        for (let aSection of this.ctx.schema.readSections()) {
            for (let aField of aSection?.fields ?? []) {
                const name = typeof aField === 'string' ? aField : aField?.name;

                if (name == fieldName) {
                    return index;
                }
            }

            index++;
        }

        //no section found for field
        return -1;
    }

    /**
     * Handles changes to field properties and updates them
     */
    private handleFieldChanges(data: any) {

        if (data.inputName === 'selectable_as_parent') {
            this.ctx.schema.setSelectableAsParent(!!data.newValue);
            this.highlight.updateHighlightState();
            return;
        }

        if (data.elementType == 'section') {
            this.deps.validationService.updateSectionKey(data?.previousName, data?.fieldName)
        }
        if (data.inputName == "hideField") {
            this.handleHideFields(data);
            return;
        }

        const newValue: any = data?.newValue;
        const inputName: string = data?.inputName;
        let fieldName: string = data?.fieldName;

        if (data.inputName === "name") {
            fieldName = data?.previousName;
        }

        let index = -1;

        if (data.elementType == "section" || data?.elementType == "multi-data-section") {
            index = this.getSectionIndexForName(fieldName);
            const modelSections = this.ctx.schema.readSections();
            const sectionIndex = this.ctx.activeIndex !== null ? this.ctx.activeIndex : index;

            // Any stale focus index must fall through rather than write past the end of the list.
            if (sectionIndex >= 0 && sectionIndex < modelSections.length) {
                modelSections[sectionIndex][inputName] = newValue;
                if (this.ctx.sections[sectionIndex]) {
                    this.ctx.sections[sectionIndex][inputName] = newValue;
                }
            }

            this.syncSectionIdentifiers();
        } else {
            if (data.inputName == "name") {
                this.updateHiddenFields(data?.previousName, data?.newValue);
            }

            index = this.getFieldIndexForName(fieldName);

            if (index >= 0) {
                this.ctx.schema.readFields()[index][inputName] = newValue;
            }
        }

        this.refreshFieldIdentifiers();
        this.highlight.updateHighlightState();
    }

    private getFieldIndexForName(targetName: string): number {
        return BuilderUtils?.getFieldIndexForName(this.ctx.schema, targetName);
    }

    private getSectionIndexForName(targetName: string): number {
        return BuilderUtils?.getSectionIndexForName(this.ctx.schema, targetName);
    }

    /* --------------------------------------------------- FIELD DND ---------------------------------------------------- */

    /**
     * Handles the event when a field is dropped into a section.
     */
    public onFieldDrop(event: DndDropEvent, section: BuilderSection) {
        this.highlight.updateSectionFieldStatus()
        if (!this.policy.canDropFieldsIntoSection(section)) {
            return;
        }

        const fieldData = event?.data;

        // The Location special control must never live inside a multi-data-section. The sidebar and the
        // in-section dnd types already prevent this, but a location field can be dragged out of a normal
        // section, so guard the drop itself as the single, authoritative choke point.
        if (section?.type === 'multi-data-section' && fieldData?.type === 'location') {
            return;
        }

        if (section && (event?.dropEffect === 'copy' || event?.dropEffect === 'move')) {
            let index = event?.index;

            this.ctx.initialIdentifier = section?.name;
            if (typeof index === 'undefined') {
                index = section?.fields?.length;
            }

            if (this.isExistingField(fieldData)) {
                this.moveField(fieldData, section, index);
                this.ctx.draggedField = null;
                this.deps.validationService?.setSectionValid(section?.name, true);
                this.refreshFieldIdentifiers();
                this.highlight.updateHighlightState();
                return;
            }

            this.ctx.newFields?.push(fieldData);
            const fields = this.ctx.schema.readFields();
            fields.push(fieldData);
            this.ctx.schema.writeFields(fields);

            section?.fields?.splice(index, 0, fieldData);
            this.commitSections();
            this.deps.validationService?.setSectionValid(section?.name, true);

            // Recompute status now
            this.refreshFieldIdentifiers();
            this.highlight.updateHighlightState();
        }
    }

    public onFieldDragStart(field: any, section: BuilderSection, index: number): void {
        this.ctx.draggedField = { field, section, index };
    }

    private isExistingField(field: any): boolean {
        if (!field?.name) {
            return false;
        }

        return this.ctx.schema.readFields().some(modelField => modelField === field || modelField?.name === field.name);
    }

    private moveField(field: any, targetSection: BuilderSection, targetIndex: number): void {
        const sourceSection = this.ctx.draggedField?.field?.name === field?.name
            ? this.ctx.draggedField.section
            : this.findSectionContainingField(field);

        if (!sourceSection || !this.policy.canDropFieldsIntoSection(sourceSection)) {
            return;
        }

        const sourceIndex = sourceSection.fields?.findIndex(sourceField => sourceField === field || sourceField?.name === field?.name) ?? -1;
        if (sourceIndex < 0) {
            return;
        }

        const [movedField] = sourceSection.fields.splice(sourceIndex, 1);

        const nextIndex = sourceSection === targetSection && targetIndex > sourceIndex
            ? targetIndex - 1
            : targetIndex;

        targetSection.fields.splice(nextIndex, 0, movedField);
        this.commitSections();
    }

    private findSectionContainingField(field: any): BuilderSection | null {
        return this.ctx.sections.find(section =>
            section?.fields?.some(sectionField => sectionField === field || sectionField?.name === field?.name)
        ) ?? null;
    }

    /* ------------------------------------------------- SECTION REMOVAL ------------------------------------------------ */

    /**
     * Removes a section from the model and updates the relevant metadata and fields.
     */
    public removeSection(item: BuilderSection, sectionIndex: number) {
        if (!this.policy.canRemoveSection(item)) {
            return;
        }

        const guard = this.deps.deletionGuard;

        if (this.ctx.mode === CmdbMode.Edit
            && guard?.sectionContainsLocationField(item, this.ctx.schema.readFields())
            && !guard.canDelete('section')) {
            return;
        }

        this.performSectionRemoval(item, sectionIndex);
    }

    private performSectionRemoval(item: BuilderSection, sectionIndex: number): void {
        this.realignActiveIndex(sectionIndex);

        this.templateManager.handleGlobalTemplates(item);
        this.deps.sectionIdentifierService?.removeSection(sectionIndex);

        const modelSections = this.ctx.schema.readSections();
        const index = sectionIndex >= 0
            ? sectionIndex
            : modelSections?.indexOf(item);

        if (index !== -1) {
            if (item.type === 'section' || item.type === 'multi-data-section') {
                const modelFields = this.ctx.schema.readFields();
                const fields = modelSections[index]?.fields ?? [];

                for (const field of fields) {
                    const fieldName = typeof field === 'string' ? field : field['name'];
                    const fieldIdx = modelFields.map(x => x?.name).indexOf(fieldName);
                    if (fieldIdx !== -1) {
                        modelFields.splice(fieldIdx, 1);
                    }
                }

                this.ctx.schema.writeFields(modelFields);

            } else if (item.type === 'ref-section') {
                this.removeRefSectionSelectionField(item);
            }

            this.ctx.sections.splice(index, 1);
            modelSections.splice(index, 1);
            this.ctx.schema.writeSections(modelSections);
            this.syncSectionIdentifiers();

            this.highlight.updateHighlightState()
            this.refreshFieldIdentifiers()

            this.deps.validationService.setSectionValid(item?.name, true);
            this.releaseDuplicateLockIfResolved();
        }
    }

    /**
     * `activeIndex` is the focused section's position and outranks the by-name lookup when a section
     * edit is applied. Removing a section above it shifts it, so it has to follow - otherwise the
     * next edit lands on the wrong section, or past the end of the list.
     */
    private realignActiveIndex(removedIndex: number): void {
        if (this.ctx.activeIndex === null) {
            return;
        }

        if (this.ctx.activeIndex === removedIndex) {
            this.ctx.activeIndex = null;
        } else if (this.ctx.activeIndex > removedIndex) {
            this.ctx.activeIndex -= 1;
        }
    }

    /* -------------------------------------------------- FIELD REMOVAL ------------------------------------------------- */

    /**
     * Removes a field from the model and section, updates the validation state, and refreshes the UI.
     */
    public removeField(item: any, section: BuilderSection) {
        if (!this.policy.canRemoveField(item) || !this.policy.canDropFieldsIntoSection(section)) {
            return;
        }

        const guard = this.deps.deletionGuard;

        if (this.ctx.mode === CmdbMode.Edit
            && guard?.isLocationField(item)
            && !guard.canDelete('field')) {
            return;
        }

        this.performFieldRemoval(item, section);
    }

    private performFieldRemoval(item: any, section: BuilderSection): void {
        const modelFields = this.ctx.schema.readFields();
        const indexField: number = modelFields?.indexOf(item);

        if (indexField > -1) {
            let removedFieldName = modelFields[indexField]?.name;
            modelFields?.splice(indexField, 1);
            this.ctx.schema.writeFields(modelFields);
            this.deps.validationService?.updateFieldValidityOnDeletion(removedFieldName);
        }

        const sectionFieldIndex = section?.fields?.indexOf(item);

        if (sectionFieldIndex > -1) {
            section?.fields?.splice(sectionFieldIndex, 1);
        }

        this.ctx.schema.writeSections(this.ctx.schema.readSections());

        let numberOfFields = section?.fields?.length > 0;

        if (!numberOfFields) {
            this.deps.validationService?.setSectionValid(section?.name, false);
        }

        this.highlight.updateHighlightState()
        this.refreshFieldIdentifiers()
        this.releaseDuplicateLockIfResolved();
    }

    /* ------------------------------------------------- DUPLICATE LOCK ------------------------------------------------- */

    /**
     * A duplicate section/field identifier latches `disableFields` (locking the whole builder) via the
     * config-edit `isDuplicate` event. Renaming back clears it, but removing the conflicting section/field
     * never routed through that event, leaving the builder stuck. After a removal we therefore re-check the
     * whole model and release the lock once no duplicate identifiers remain anywhere.
     */
    private releaseDuplicateLockIfResolved(): void {
        if (this.ctx.disableFields && !this.hasAnyDuplicateIdentifier()) {
            this.ctx.activeDuplicateField = null;
            this.setDisableFields(false);
        }
    }

    private hasAnyDuplicateIdentifier(): boolean {
        return this.hasDuplicateNames((this.ctx.sections ?? []).map(section => section?.name))
            || this.hasDuplicateNames(this.ctx.schema.readFields().map(field => field?.name));
    }

    private hasDuplicateNames(names: Array<string | undefined>): boolean {
        const seen = new Set<string>();

        for (const name of names) {
            if (!name) {
                continue;
            }
            if (seen.has(name)) {
                return true;
            }
            seen.add(name);
        }

        return false;
    }
}
