/*
* DATAGERRY - OpenSource Enterprise CMDB
* Copyright (C) 2025 becon GmbH
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
import {
    AfterViewChecked,
    ChangeDetectionStrategy,
    Component,
    EventEmitter,
    Input,
    OnDestroy,
    Output,
} from '@angular/core';

import { ReplaySubject } from 'rxjs';

import { DndDropEvent, DropEffect } from 'ngx-drag-drop';
import { NgbModal } from '@ng-bootstrap/ng-bootstrap';


import { CmdbMode } from '../../modes.enum';

import { CmdbRelation, CmdbRelationSection, RelationSection } from '../../models/relation.model';
import { TextControl } from '../../type/builder/controls/text/text.control';
import { NumberControl } from '../../type/builder/controls/number/number.control';
import { PasswordControl } from '../../type/builder/controls/text/password.control';
import { TextAreaControl } from '../../type/builder/controls/text/textarea.control';
import { CheckboxControl } from '../../type/builder/controls/choice/checkbox.control';
import { RadioControl } from '../../type/builder/controls/choice/radio.control';
import { SelectControl } from '../../type/builder/controls/choice/select.control';
import { DateControl } from '../../type/builder/controls/date-time/date.control';
import { SectionControl } from '../../type/builder/controls/section.control';
import { Controller } from '../../type/builder/controls/controls.common';
import { BuilderUtils } from './utils/builder-utils';
import { SectionIdentifierService } from '../../type/services/SectionIdentifierService.service';
import { ValidationService } from '../../type/services/validation.service';
import { FieldIdentifierValidationService } from '../../type/services/field-identifier-validation.service';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'cmdb-builder',
    templateUrl: './builder.component.html',
    styleUrls: ['./builder.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush
})
export class BuilderComponent implements OnDestroy, AfterViewChecked {

    @Input() public mode = CmdbMode.View;
    @Input() public valid: boolean = true;
    @Input('relationInstance')
    public set RelationInstance(instance: CmdbRelation) {
        this.relationInstance = instance;
        if (instance !== undefined) {
            const preSectionList: any[] = [];
            for (const section of instance.sections) {
                preSectionList.push(section);
                const fieldBufferList = [];
                for (const field of section.fields) {
                    const found = instance.fields.find(f => f.name === field);
                    if (found) {
                        fieldBufferList.push(found);
                    }
                }
                preSectionList.find(s => s.name === section.name).fields = fieldBufferList;
            }
            this.sections = preSectionList;
        }
    }

    @Output() public validChange: EventEmitter<boolean> = new EventEmitter<boolean>();

    private subscriber: ReplaySubject<void> = new ReplaySubject<void>();
    public MODES: typeof CmdbMode = CmdbMode;

    private eventIndex: number;
    private onSectionMoveIndex: number;
    private activeIndex: number | null = null;

    public sections: RelationSection[] = [];
    public relationInstance: CmdbRelation;
    public sectionIdenfier: Array<String> = [];
    public initialIdentifier: string = '';
    public newSections: Array<RelationSection> = [];
    public newFields: Array<RelationSection> = [];

    private activeDuplicateField: { sectionIndex: number; fieldIndex: number } | null = null;
    public disableFields: boolean = false;

    // Flags to store previous highlight states
    private prevSectionHighlighted: boolean = false;
    private prevFieldHighlighted: boolean = false;

    public structureControls = [
        new Controller('section', new SectionControl()),
    ];


    public basicControls = [
        new Controller('text', new TextControl()),
        new Controller('number', new NumberControl()),
        new Controller('password', new PasswordControl()),
        new Controller('textarea', new TextAreaControl()),
        new Controller('checkbox', new CheckboxControl()),
        new Controller('radio', new RadioControl()),
        new Controller('select', new SelectControl()),
        new Controller('date', new DateControl())
    ];

    /* ------------------------------------------------------------------------------------------------------------------ */
    /*                                                     LIFE CYCLE                                                     */
    /* ------------------------------------------------------------------------------------------------------------------ */

    public constructor(private modalService: NgbModal, private validationService: ValidationService,
        public sectionIdentifierService: SectionIdentifierService, private fieldIdentifierValidation: FieldIdentifierValidationService,
    ) {
        this.relationInstance = new CmdbRelation();
    }


    ngOnInit(): void {
        this.updateHighlightState();
    }


    ngOnDestroy(): void {
        this.subscriber?.next();
        this.subscriber?.complete();
        this.sectionIdentifierService?.resetIdentifiers();
        this.validationService?.cleanup();
        this.fieldIdentifierValidation?.clearFieldNames();
    }


    ngAfterViewChecked(): void {
        this.checkAndUpdateHighlightState()
    }


    /* ------------------------------------------------ FIELD ITERACTIONS ----------------------------------------------- */


    onDragStart(index: number) {
        this.activeIndex = null
        this.onSectionMoveIndex = index;
    }

    /**
     * Handels dropping any kind of section in the drop area
     * 
     * @param event DropEvent containing the section as data
     */
    public onSectionDrop(event: DndDropEvent): void {
        event.event.preventDefault();
        let sectionData = event.data;



        if (!this.sections || !Array.isArray(this.sections)) {
            console.error("Sections array is undefined or not an array, initializing...");
            this.sections = [];
        }

        if (!sectionData || typeof sectionData !== 'object') {
            console.error("Dropped section data is invalid", event.data);
            return;
        }

        if (!sectionData.fields || !Array.isArray(sectionData.fields)) {
            sectionData.fields = [];
        }

        let index = event.index ?? this.sections.length;

        this.sections.splice(index, 0, sectionData);

        this.relationInstance.sections = [...this.sections];

        this.sectionIdentifierService.getDroppedIndex(index);
        this.sectionIdentifierService.addSection(sectionData.name, sectionData.name, index);

        this.validationService.setSectionValid(sectionData.name, sectionData.fields.length > 0);
        this.updateSectionFieldStatus();
        this.updateHighlightState();
    }


    /**
     * Redirects changes to field properties
     * @param data new data for field
     */
    public onFieldChange(data: any, sectionIndex: number, fieldIndex: number) {
        if (data.hasOwnProperty("isDuplicate") && data.isDuplicate) {

            // Set the current field as the active duplicate and set disableFields to true
            this.activeDuplicateField = { sectionIndex, fieldIndex };
            this.disableFields = true;
        } else {

            // Reset the active duplicate field and disableFields flag when no duplication issue exists
            this.activeDuplicateField = null;
            this.disableFields = false;
            this.handleFieldChanges(data);
        }
    }


    /**
     * Handles changes to field properties and updates them
     * @param data new data for field
     */
    private handleFieldChanges(data: any) {

        if (data.elementType == 'section') {
            this.validationService.updateSectionKey(data.previousName, data.fieldName)
        }
        // if (data.inputName == "hideField") {
        //     this.handleHideFields(data);
        //     return;
        // }

        const newValue: any = data.newValue;
        const inputName: string = data.inputName;
        let fieldName: string = data.fieldName;

        if (data.inputName === "name") {
            fieldName = data.previousName;
        }

        let index = -1;

        if (data.elementType == "section") {
            index = this.getSectionIndexForName(this.relationInstance, fieldName);

            if (this.activeIndex !== null) {
                this.relationInstance.sections[this.activeIndex][inputName] = newValue;
            }
            else if (index >= 0) {
                this.relationInstance.sections[index][inputName] = newValue;
            }
        } else {


            index = this.getFieldIndexForName(this.relationInstance, fieldName);

            if (index >= 0) {
                this.relationInstance.fields[index][inputName] = newValue;
            }
        }

        //  this.refreshFieldIdentifiers();
        this.updateHighlightState();
    }

    getSectionIndexForName(typeInstance: CmdbRelation, targetName: string): number {
        let index = 0;
        for (let section of typeInstance.sections) {
            if (section.name === targetName) {
                return index;
            } else {
                index += 1;
            }
        }
        return -1;
    }

    getFieldIndexForName(typeInstance: CmdbRelation, targetName: string): number {
        let index = 0;
        for (let field of typeInstance.fields) {
            if (field.name === targetName) {
                return index;
            } else {
                index += 1;
            }
        }
        return -1;
    }



    /**
     * Handles the event when a field is dropped into a section. 
     * Updates the section field status, checks if the section is global, and processes the drop event.
     * Adds the dropped field data into the section and updates the relation instance metadata.
     * @param event - The drop event, containing field data and drop effect.
     * @param section - The section where the field is dropped.
     */
    public onFieldDrop(event: DndDropEvent, section: CmdbRelationSection) {
        this.updateSectionFieldStatus()
        if (!this.relationInstance.fields) {
            this.relationInstance.fields = [];
        }


        const fieldData = event.data;

        if (section && (event.dropEffect === 'copy' || event.dropEffect === 'move')) {
            let index = event.index;

            this.initialIdentifier = section.name;
            if (typeof index === 'undefined') {
                index = section?.fields?.length;
            }

            if (event.dropEffect === 'copy') {
                this.newFields?.push(fieldData);
            }

            section?.fields?.splice(index, 0, fieldData);
            this.relationInstance.sections = [...this.sections];
            this.relationInstance?.fields?.push(fieldData);
            this.relationInstance.fields = [...this.relationInstance?.fields];
            this.validationService?.setSectionValid(section?.name, true);
        }
    }


    public onFieldDragged(item: any, section: CmdbRelationSection) {


        const sectionIndex = section?.fields.indexOf(item);
        section?.fields?.splice(sectionIndex, 1);
        const fieldIndex = this.relationInstance?.fields?.indexOf(item);
        let updatedDraggedFieldName = this.relationInstance?.fields[fieldIndex]?.name;

        this.relationInstance?.fields?.splice(fieldIndex, 1);
        this.relationInstance.fields = [...this.relationInstance.fields];
        this.validationService?.setIsValid(updatedDraggedFieldName, true)

        // this.refreshFieldIdentifiers();
        this.updateHighlightState();

    }

    /**
     * Handles the drag event of a section and updates the section list based on the drag-and-drop effect.
     * If the drag effect is 'move', the section is removed from its original position, 
     * and the section indexes and highlight states are updated accordingly.
     * @param item - The section being dragged.
     * @param list - The list of sections.
     * @param effect - The effect of the drag-and-drop operation (e.g., 'move').
     */
    public onSectionDragged(item: any, list: any[], effect: DropEffect) {
        if (effect === 'move') {
            const index = list.indexOf(item);
            list?.splice(index, 1);
            this.sections = list;
            this.relationInstance.sections = [...this.sections];
            this.sectionIdentifierService?.updateSectionIndexes(this.onSectionMoveIndex, this.eventIndex);
            this.updateHighlightState();
            // this.refreshFieldIdentifiers();
        }
    }


    /**
     * Removes a section from the relationInstance and updates the relevant metadata and fields.
     *
     * @param item The section item to be removed.
     * @param sectionIndex The index of the section to be removed.
     */
    public removeSection(item: RelationSection, sectionIndex: number) {

        if (this.activeIndex === sectionIndex) {
            this.activeIndex = null
        }

        this.sectionIdentifierService.removeSection(sectionIndex);

        const index: number = this.relationInstance.sections.indexOf(item);

        if (index !== -1) {
            if (item.type === 'section') {
                const fields: Array<string> = this.relationInstance.sections[index].fields;
                for (const field of fields) {
                    const fieldIdx = this.relationInstance.fields.map(x => x.name).indexOf(field['name']);
                    if (fieldIdx !== -1) {
                        this.relationInstance.fields.splice(fieldIdx, 1);
                    }
                }

                this.relationInstance.fields = [...this.relationInstance.fields];

            }

            this.sections.splice(index, 1);
            this.relationInstance.sections.splice(index, 1);
            this.relationInstance.sections = [...this.relationInstance.sections];

            this.updateHighlightState()
            // this.refreshFieldIdentifiers()

            this.validationService.setSectionValid(item.name, true);
        }
    }


    /**
     * Removes a field from the relation instance and section, updates the validation state, and refreshes the UI.
     * @param item - The field item to be removed.
     * @param section - The section from which the field will be removed.
     */
    public removeField(item: any, section: RelationSection) {
        const indexField: number = this.relationInstance.fields.indexOf(item);

        if (indexField > -1) {
            let removedFieldName = this.relationInstance.fields[indexField].name;
            this.relationInstance.fields.splice(indexField, 1);
            this.relationInstance.fields = [...this.relationInstance.fields];
            this.validationService.updateFieldValidityOnDeletion(removedFieldName);
        }

        const sectionFieldIndex = section.fields.indexOf(item);

        if (sectionFieldIndex > -1) {
            section.fields.splice(sectionFieldIndex, 1);
        }

        this.relationInstance.sections = [...this.relationInstance.sections];

        let numberOfFields = section.fields.length > 0;

        if (!numberOfFields) {
            this.validationService.setSectionValid(section.name, false);
        }

        this.updateHighlightState()
        // this.refreshFieldIdentifiers()
    }


    /**
     * Determines if a cmdb-config-edit component should be disabled based on the section and field indices.
     * @param sectionIndex - The index of the section.
     * @param fieldIndex - The index of the field within the section.
     * @returns A boolean indicating whether the component should be disabled.
     */
    public isConfigEditDisabled(sectionIndex: number, fieldIndex: number): boolean {

        // If disableFields is true, disable all fields except the activeDuplicateField
        if (this.disableFields) {
            this.validationService.setDisableFields(true)
            return !(
                this.activeDuplicateField?.sectionIndex === sectionIndex &&
                this.activeDuplicateField?.fieldIndex === fieldIndex
            );
        }
        this.validationService.setDisableFields(false)
        this.updateHighlightState()

        // If no active duplicate, all components are enabled
        return false;
    }


    /**
     * Checks if a section has fields.
     * @param section - The section to check.
     * @returns - True if the section has fields, otherwise false.
     */
    isSectionHasField(section: any): boolean {
        // this.updateHighlightState()
        return section?.fields?.length > 0;
    }


    /**
     * Checks if any section lacks fields and updates the save button status.
     */
    updateSectionFieldStatus(): void {
        const allSectionsHaveFields = this.sections?.every(section => section.fields.length > 0);

        // Set the save button disabled state based on section status
        this.validationService.setSectionWithoutFieldState(allSectionsHaveFields);
    }


    /**
     * Determines if a section should be highlighted based on various conditions.
     * A section is highlighted if it has a duplicate name, missing name or label,
     * or if any of its fields are highlighted (missing name, label, or are duplicates).
     * @param section - The section to be checked.
     * @returns boolean - Returns true if the section or any of its fields are highlighted, false otherwise.
     */
    public isSectionHighlighted(section: any): boolean {
        const isDuplicateIdentifier = this.sections.filter(s => s.name === section.name).length > 1;
        const hasInvalidFields = section.fields?.some(field => this.isFieldHighlighted(field, section.fields));

        // Check for section-level issues (name, label, duplicates)
        const hasSectionIssues = !section.name || isDuplicateIdentifier || !section.label;


        // If the section has issues or any of its fields are invalid, highlight the section
        return hasSectionIssues || hasInvalidFields;
    }


    /**
     * Determines if a field should be highlighted based on its properties.
     * Checks for invalid identifiers, missing labels, and reference fields with invalid reference.
     * @param field - The field to check for highlighting.
     * @param sectionfields - The list of all section fields for checking duplicate names.
     * @returns boolean - Returns true if the field should be highlighted, false otherwise.
     */
    public isFieldHighlighted(field: any, sectionfields: any): boolean {
        // Ensure field is a valid object (not null, undefined, or a primitive)
        if (!field || typeof field !== 'object') {
            return false;
        }
        const isRefField = field.type === "ref";
        const hasInvalidIdentifier = !field.name || sectionfields.filter(s => s.name === field.name).length > 1;
        const hasValidRefTypes = field && 'ref_types' in field && Array.isArray(field.ref_types) && field.ref_types.length > 0;

        if (hasInvalidIdentifier || isRefField || !field.label) {
            if (isRefField) {

                const hasSummaries = field.summaries?.every(
                    ({ type_id, line }) => type_id != null && line?.trim() !== "" && line !== null
                );

                return !hasValidRefTypes || hasInvalidIdentifier || !field.label || !hasSummaries;
            }
            return true;
        }

        return false;
    }


    /**
     * Prevents drag events when any section is highlighted.
     * If a section is highlighted, this function stops the drag event while allowing other button interactions.
     * @param event - The drag event to be checked and possibly prevented.
     */
    public preventDragForAllSections(event: DragEvent): void {
        const isAnyHighlighted = this.sections.some(section => this.isSectionHighlighted(section));
        if (isAnyHighlighted || this.disableFields) {
            event.stopPropagation(); // Stops event from affecting other elements
            event.preventDefault();  // Prevent dragging behavior
        }
    }


    /**
     * Prevents drag events for all fields within a section if any field in the section is highlighted.
     * @param event - The drag event to be checked and possibly prevented.
     * @param section - The section that contains the fields.
     */
    public preventDragForAllFields(event: DragEvent, section: any): void {
        // Check if any field in the section is highlighted (has an error)
        const isAnyFieldHighlighted = section.fields.some(field => this.isFieldHighlighted(field, section.fields));
        const isAnyFieldEmpty = this.checkEmptyFields().length > 0;

        if (isAnyFieldHighlighted || isAnyFieldEmpty || this.disableFields) {
            event.stopPropagation();  // Stops event from affecting other elements
            event.preventDefault();   // Prevent dragging behavior
        }
    }


    /**
     * Updates the highlight state of sections and fields based on their current highlight status.
     * Checks if any section or field is highlighted and sets their respective states
     * in the validation service.
     */
    updateHighlightState(): void {
        const isSectionHighlighted = this.isAnySectionHighlighted();
        const isFieldHighlighted = this.isAnyFieldHighlighted();

        this.updateSectionFieldStatus()
        this.validationService.setSectionHighlightState(isSectionHighlighted);
        this.validationService.setFieldHighlightState(isFieldHighlighted);

        const hasEmptyFields = this.checkEmptyFields().length > 0;
        this.validationService.setDisableFields(hasEmptyFields);
    }


    /**
     * Checks if any section is highlighted by evaluating the sections array.
     * @returns A boolean indicating if any section is currently highlighted.
     */
    isAnySectionHighlighted(): boolean {
        return this.sections.some(section =>
            this.isSectionHighlighted(section)
        );
    }


    /**
     * Checks if any field within the sections is highlighted.
     * Iterates through all sections and their fields to determine if a field is highlighted.
     * @returns true if any field is highlighted, false otherwise.
     */
    isAnyFieldHighlighted(): boolean {
        return this.sections.some(section =>
            section.fields.some(field => this.isFieldHighlighted(field, section.fields))
        );
    }


    /**
     * Checks for empty field names in each section and returns an array of objects 
     * containing the indices of sections and fields with empty or missing names.
     * @returns An array of objects with `sectionIndex` and `fieldIndex` for each field with an empty name.
     */
    checkEmptyFields(): Array<{ sectionIndex: number, fieldIndex: number }> {
        return this.sections.flatMap((section, sectionIndex) =>
            section.fields
                .map((field, fieldIndex) => {
                    if (!field.name || field.name.trim() === '') {
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
    checkAndUpdateHighlightState(): void {
        // Check current highlight states
        const isSectionHighlighted = this.isAnySectionHighlighted();
        const isFieldHighlighted = this.isAnyFieldHighlighted();

        // Only update if the highlight state has changed
        if (isSectionHighlighted !== this.prevSectionHighlighted || isFieldHighlighted !== this.prevFieldHighlighted) {
            this.updateHighlightState();

            // Store the current states as the new previous states
            this.prevSectionHighlighted = isSectionHighlighted;
            this.prevFieldHighlighted = isFieldHighlighted;
        }
    }


    /**
     * Checks if any empty fields exist for a specific section and field index.
     * @param sectionIndex - The index of the section to check.
     * @param fieldIndex - The index of the field within the section to check.
     * @returns A boolean indicating whether empty fields exist at the given section and field index.
     */

    isEmptyFielsExist(sectionIndex: number, fieldIndex: number): boolean {
        const emptyFields = this.checkEmptyFields();
        if (emptyFields.length === 0) {
            return false;
        }
        return !emptyFields.some(emptyField => emptyField.sectionIndex === sectionIndex && emptyField.fieldIndex === fieldIndex);
    }


    /**
     * Checks if the current section is locked based on empty fields.
     * If there are any empty fields, interactions are locked.
     * @returns {boolean} - Returns true if any fields are empty, otherwise false.
     */
    isLocked(): boolean {
        // Lock all interactions if there are any empty fields
        return this.checkEmptyFields().length > 0;
    }


    public getDnDEffectAllowedForField(field: any) {
        return "move";
    }

    /**
     * This prevents the special control "Location" to be placed inside an multi-data-section
     * 
     * @param sectionR
     * @returns allowed types for a section
     */
    public getInputType(sectionType: string) {

        return ['inputs'];

    }


    public getSectionCollapseIcon(section: RelationSection) {
        return ['far', 'edit'];
    }



    /**
     * Sets the active index for the current section and updates the section identifier service.
     * @param index - The new active index to set.
     */
    setActiveIndex(index: number) {
        this.activeIndex = index;
        this.sectionIdentifierService.setActiveIndex(index);
    }


    /* ----------------------------------------------- CSS CLASS HANDLERS ------------------------------------------------ */


    /**
     * Returns the CSS classes for a section header based on its state.
     * Applies styles for global sections and highlighted headers.
     * @param section - The section to evaluate.
     */
    getSectionHeaderClass(section: any): any {
        return {
            'highlight-section-header': this.isSectionHighlighted(section) || !this.isSectionHasField(section)
        };
    }

    /**
     * Returns the CSS classes for a draggable item based on section state.
     * Applies 'disabled' class if any section is highlighted or fields are disabled.
     */
    getDraggableItemClass(): any {
        return {
            'disabled': this.isAnySectionHighlighted() || this.disableFields
        };
    }


    /* ------------------------------------------------ HELPER FUNCTIONS ------------------------------------------------ */


    /**
     * Checks if the given section is new by comparing it to the list of new sections.
     * @param section - The section to check.
     * @returns `true` if the section is new, otherwise `false`.
     */
    isNewSection(section: RelationSection): boolean {
        return BuilderUtils.isNewSection(section, this.newSections);
    }


    /**
     * Checks if the given field is new by comparing it to the list of new fields.
     * @param field - The field to check.
     * @returns `true` if the field is new, otherwise `false`.
     */
    isNewField(field: any): boolean {
        return BuilderUtils.isNewField(field, this.newFields);
    }


    /**
     * Matches a given value to a corresponding type string.
     * @param value - The value to match.
     * @returns The matched type as a string.
     */
    matchedType(value: string): string {
        return BuilderUtils.matchedType(value);
    }
}
