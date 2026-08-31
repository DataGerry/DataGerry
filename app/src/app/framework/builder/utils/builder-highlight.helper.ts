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
import { isReservedIdentifier } from '../../../layout/validators/reserved-identifier-prefix-validator';
import { ValidationService } from 'src/app/framework/builder/services/validation.service';
import { CmdbMode } from '../../modes.enum';
import { BuilderContext } from './builder-context';
import { BuilderInteractionPolicy } from './builder-interaction-policy';
import { BuilderModeResolver } from './builder-mode.resolver';

/**
 * Owns the builder's highlight / validation-presentation logic: which sections and fields must be
 * flagged as invalid, whether interactions should be locked, and the derived CSS 
 */
export class BuilderHighlightHelper {
    /** Shared by every draggable control, so the value is global rather than per item. */
    private readonly draggableItemClass = { disabled: false };

    private readonly modes: BuilderModeResolver;

    constructor(
        private readonly ctx: BuilderContext,
        private readonly policy: BuilderInteractionPolicy,
        private readonly validationService: ValidationService,
        modes?: BuilderModeResolver
    ) {
        this.modes = modes ?? new BuilderModeResolver(ctx, policy);
    }

    /**
     * Determines if a cmdb-config-edit component should be disabled based on the section and field indices.
     */
    public isConfigEditDisabled(sectionIndex: number, fieldIndex: number): boolean {
        if (!this.ctx.disableFields) {
            return false;
        }

        return !(
            this.ctx.activeDuplicateField?.sectionIndex === sectionIndex &&
            this.ctx.activeDuplicateField?.fieldIndex === fieldIndex
        );
    }

    /**
     * Checks if a section has fields.
     */
    public isSectionHasField(section: any): boolean {
        return section?.fields?.length > 0;
    }

    /**
     * Checks if any section lacks fields and updates the save button status.
     */
    public updateSectionFieldStatus(): void {
        const allSectionsHaveFields = this.ctx.sections?.every(section => section?.fields?.length > 0);

        // Set the save button disabled state based on section status
        this.validationService.setSectionWithoutFieldState(allSectionsHaveFields);
    }

    /**
     * Determines if a section should be highlighted based on various conditions.
     */
    public isSectionHighlighted(section: any): boolean {
        // Predefined / non-editable sections (global templates, special-type, system) are defined by us
        // and trusted, so they and their fields are never flagged.
        if (!this.policy.canEditSection(section)) {
            return false;
        }

        const isDuplicateIdentifier = this.ctx.sections?.filter(s => s?.name === section?.name).length > 1;
        const isRefSection = section?.type === "ref-section";
        const hasInvalidFields = section?.fields?.some(field => this.isFieldHighlighted(field, section));
        const usesReservedName = this.flagsReservedName(section?.name, this.modes.sectionMode(section));

        // Check for section-level issues (name, label, duplicates)
        const hasSectionIssues = !section?.name || isDuplicateIdentifier || !section?.label || usesReservedName;

        if (isRefSection) {
            const isInvalidReference = !section?.reference?.type_id || !section?.reference?.section_name;
            return isInvalidReference || hasSectionIssues;
        }

        // If the section has issues or any of its fields are invalid, highlight the section
        return hasSectionIssues || hasInvalidFields;
    }

    /**
     * Determines if a field should be highlighted based on its properties.
     */
    public isFieldHighlighted(field: any, section?: any): boolean {
        // Ensure field is a valid object (not null, undefined, or a primitive)
        if (!field || typeof field !== 'object') {
            return false;
        }

        // A field inside a predefined / non-editable section (global template, special-type, system) is
        // defined by us and is never flagged - not even for duplicates, since the user cannot change it.
        if (section && !this.policy.canEditSection(section)) {
            return false;
        }

        const hasDuplicateIdentifier = this.hasDuplicateFieldIdentifier(field);
        // Locked fields (special-type schema or global template fields) are not user-editable, so only a
        // real duplicate identifier matters for them.
        if (this.policy.isLockedField(field)) {
            return hasDuplicateIdentifier;
        }

        const isRefField = field?.type === "ref";
        // The reserved "dg-"/"dg_" prefix rule only targets user-created identifiers. The location
        // special control ships with the system-owned "dg_location" name, which the user cannot edit,
        // so it legitimately uses the reserved namespace and must not be flagged.
        const isSystemReservedField = field?.type === 'location';
        const usesReservedName = !isSystemReservedField && this.flagsReservedName(field?.name, this.modes.fieldMode(field));
        const hasInvalidIdentifier = !field?.name || hasDuplicateIdentifier || usesReservedName;
        const hasValidRefTypes = field && 'ref_types' in field && Array.isArray(field?.ref_types) && field?.ref_types?.length > 0;

        if (hasInvalidIdentifier || isRefField || !field?.label) {
            if (isRefField) {

                const hasSummaries = field.summaries?.every(
                    ({ type_id, line }) => type_id != null && line?.trim() !== "" && line !== null
                );

                return !hasValidRefTypes || hasInvalidIdentifier || !field?.label || !hasSummaries;
            }
            return true;
        }

        return false;
    }

    /**
     * Updates the highlight state of sections and fields based on their current highlight status.
     */
    public updateHighlightState(): void {
        const isSectionHighlighted = this.isAnySectionHighlighted();
        const isFieldHighlighted = this.isAnyFieldHighlighted();

        this.updateSectionFieldStatus();
        this.validationService?.setSectionHighlightState(isSectionHighlighted);
        this.validationService?.setFieldHighlightState(isFieldHighlighted);

        // `checkAndUpdateHighlightState` skips its push whenever the state matches what was last
        // reported, so that record has to be written here too. The mutation paths call this method
        // directly; leaving the record behind lets it drift from what the wizard was actually told,
        // and the next real change that happens to match the stale record is then swallowed.
        this.ctx.prevSectionHighlighted = isSectionHighlighted;
        this.ctx.prevFieldHighlighted = isFieldHighlighted;
    }

    /**
     * Checks if any section is highlighted by evaluating the sections array.
     */
    public isAnySectionHighlighted(): boolean {
        return this.ctx.sections?.some(section =>
            this.isSectionHighlighted(section)
        );
    }

    /**
     * Checks if any field within the sections is highlighted.
     */
    public isAnyFieldHighlighted(): boolean {
        return this.ctx.sections.some(section =>
            section?.fields?.some(field => this.isFieldHighlighted(field, section))
        );
    }

    /**
     * Checks for empty field names in each section and returns an array of objects
     * containing the indices of sections and fields with empty or missing names.
     */
    public checkEmptyFields(): Array<{ sectionIndex: number, fieldIndex: number }> {
        return this.ctx.sections?.flatMap((section, sectionIndex) =>
            section?.fields
                .map((field, fieldIndex) => {
                    if (!field?.name || field?.name?.trim() === '') {
                        if (field.hasOwnProperty('name')) {
                            return { sectionIndex, fieldIndex };
                        }
                    }
                    return null;
                })
                .filter((result) => result !== null)
        );
    }

    /**
     * Optimized method to check if any section or field is highlighted
     * and call `updateHighlightState` only when necessary.
     */
    public checkAndUpdateHighlightState(): void {
        // Check current highlight states
        const isSectionHighlighted = this.isAnySectionHighlighted();
        const isFieldHighlighted = this.isAnyFieldHighlighted();

        // Only update if the highlight state has changed; `updateHighlightState` keeps the record.
        if (isSectionHighlighted !== this.ctx.prevSectionHighlighted || isFieldHighlighted !== this.ctx.prevFieldHighlighted) {
            this.updateHighlightState();
        }
    }

    /**
     * Checks if any empty fields exist for a specific section and field index.
     */
    public isEmptyFielsExist(sectionIndex: number, fieldIndex: number): boolean {
        const emptyFields = this.checkEmptyFields();
        if (emptyFields?.length === 0) {
            return false;
        }
        return !emptyFields?.some(emptyField => emptyField?.sectionIndex === sectionIndex && emptyField?.fieldIndex === fieldIndex);
    }

    /**
     * Checks if the current section is locked based on empty fields.
     */
    public isLocked(): boolean {
        // Lock all interactions if there are any empty fields
        return this.checkEmptyFields()?.length > 0;
    }

    /**
     * Returns the CSS classes for a section header based on its state.
     */
    public getSectionHeaderClass(section: any): any {
        return {
            'global-section-item': this.policy.isGlobalSection(section),
            'highlight-section-header': this.isSectionHighlighted(section) || !this.isSectionHasField(section)
        };
    }

    /**
     * Returns the CSS classes for a draggable item based on section state.
     *
     * The object is reused instead of rebuilt so the `[ngClass]` binding on every draggable
     * control keeps a stable reference. NgClass diffs the object's keys on each check, so
     * mutating it in place still applies the change.
     */
    public getDraggableItemClass(): { disabled: boolean } {
        this.draggableItemClass.disabled = Boolean(this.isAnySectionHighlighted() || this.ctx.disableFields);

        return this.draggableItemClass;
    }

    /**
     * Prevents drag events for all fields within a section if any field in the section is highlighted.
     */
    public preventDragForAllFields(event: DragEvent, section: any): void {
        // Check if any field in the section is highlighted (has an error)
        const isAnyFieldHighlighted = section?.fields?.some(field => this.isFieldHighlighted(field, section));
        const isAnyFieldEmpty = this.checkEmptyFields()?.length > 0;

        if (isAnyFieldHighlighted || isAnyFieldEmpty || this.ctx.disableFields || this.isAnySectionHighlighted()) {
            event?.stopPropagation();  // Stops event from affecting other elements
            event?.preventDefault();   // Prevent dragging behavior
        }
    }

    /**
     * The reserved "dg-"/"dg_" prefix is only rejected where the editor actually applies the
     * validator, i.e. where the identifier is still being authored. An identifier mounted in Edit
     * mode has had its validators cleared, so flagging it would permanently block saving a record
     * that was created before the rule existed.
     */
    private flagsReservedName(name: string, editorMode: CmdbMode): boolean {
        return editorMode === CmdbMode.Create && isReservedIdentifier(name);
    }

    private hasDuplicateFieldIdentifier(field: any): boolean {
        if (!field?.name) {
            return false;
        }

        return this.ctx.schema.readFields().filter(typeField => typeField?.name === field.name).length > 1;
    }
}
