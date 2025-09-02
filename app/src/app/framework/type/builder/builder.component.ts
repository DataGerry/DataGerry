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
    ElementRef,
    EventEmitter,
    Input,
    OnChanges,
    OnDestroy,
    Output,
    Renderer2,
    SimpleChanges
} from '@angular/core';

import { ReplaySubject } from 'rxjs';

import { v4 as uuidv4 } from 'uuid';
import { DndDropEvent, DropEffect } from 'ngx-drag-drop';
import { NgbModal } from '@ng-bootstrap/ng-bootstrap';

import { ValidationService } from '../services/validation.service';

import { Controller } from './controls/controls.common';
import { SectionControl } from './controls/section.control';
import { Group } from '../../../management/models/group';
import { User } from '../../../management/models/user';
import { TextControl } from './controls/text/text.control';
import { PasswordControl } from './controls/text/password.control';
import { TextAreaControl } from './controls/text/textarea.control';
import { ReferenceControl } from './controls/specials/ref.control';
import { LocationControl } from './controls/specials/location.control';
import { RadioControl } from './controls/choice/radio.control';
import { SelectControl } from './controls/choice/select.control';
import { CheckboxControl } from './controls/choice/checkbox.control';
import { CmdbMode } from '../../modes.enum';
import { DateControl } from './controls/date-time/date.control';
import { RefSectionControl } from './controls/ref-section.common';
import { CmdbMultiDataSection, CmdbType, CmdbTypeSection } from '../../models/cmdb-type';
import { CmdbSectionTemplate } from '../../models/cmdb-section-template';
import { MultiSectionControl } from './controls/multi-section.control';
import { SectionIdentifierService } from '../services/SectionIdentifierService.service';
import { FieldIdentifierValidationService } from '../services/field-identifier-validation.service';
import { BuilderUtils } from './utils/builder-utils';
import { NumberControl } from './controls/number/number.control';
/* ------------------------------------------------------------------------------------------------------------------ */
declare var $: any;

@Component({
    selector: 'cmdb-builder',
    templateUrl: './builder.component.html',
    styleUrls: ['./builder.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush
})
export class BuilderComponent implements OnChanges, OnDestroy, AfterViewChecked {
    private subscriber: ReplaySubject<void> = new ReplaySubject<void>();
    public MODES: typeof CmdbMode = CmdbMode;

    private eventIndex: number;
    private onSectionMoveIndex: number;
    private activeIndex: number | null = null;

    public sections: Array<any> = [];
    public typeInstance: CmdbType;
    public sectionIdenfier: Array<String> = [];
    public initialIdentifier: string = '';
    public newSections: Array<CmdbTypeSection> = [];
    public newFields: Array<CmdbTypeSection> = [];

    private activeDuplicateField: { sectionIndex: number; fieldIndex: number } | null = null;
    public disableFields: boolean = false;

    // Flags to store previous highlight states
    private prevSectionHighlighted: boolean = false;
    private prevFieldHighlighted: boolean = false;

    @Input() public sectionTemplates: Array<CmdbSectionTemplate> = [];
    @Input() public globalSectionTemplates: Array<CmdbSectionTemplate> = [];

    public selectedGlobalSectionTemplates: Array<CmdbSectionTemplate> = [];
    public globalSectionTemplateFields: Array<string> = [];

    public showColorPickerForSection: string | null = null;  // Keep track of which section's color picker is open

    @Input() public mode = CmdbMode.View;
    @Input() public groups: Array<Group> = [];
    @Input() public users: Array<User> = [];
    @Input() public types: Array<CmdbType> = [];
    @Input() public valid: boolean = true;


    @Input('typeInstance')
    public set TypeInstance(instance: CmdbType) {
        this.typeInstance = instance;
        if (instance !== undefined) {
            const preSectionList: any[] = [];
            for (const section of instance?.render_meta?.sections) {
                preSectionList?.push(section);
                const fieldBufferList = [];
                for (const field of section?.fields) {
                    const found = instance?.fields?.find(f => f?.name === field);
                    if (found) {
                        fieldBufferList?.push(found);
                    }
                }
                preSectionList.find(s => s.name === section.name).fields = fieldBufferList;
            }
            this.sections = preSectionList;
        }
    }

    @Output() public validChange: EventEmitter<boolean> = new EventEmitter<boolean>();


    public structureControls = [
        new Controller('section', new SectionControl()),
        new Controller('multi-data-section', new MultiSectionControl()),
        new Controller('ref-section', new RefSectionControl())
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


    public specialControls = [
        new Controller('ref', new ReferenceControl()),
        new Controller('location', new LocationControl())
    ];



    /* ------------------------------------------------------------------------------------------------------------------ */
    /*                                                     LIFE CYCLE                                                     */
    /* ------------------------------------------------------------------------------------------------------------------ */

    public constructor(private modalService: NgbModal, private validationService: ValidationService,
        public sectionIdentifierService: SectionIdentifierService, private fieldIdentifierValidation: FieldIdentifierValidationService,
        private renderer: Renderer2,
        private el: ElementRef,
    ) {
        this.typeInstance = new CmdbType();
    }


    ngOnInit(): void {
        this.refreshFieldIdentifiers();
        this.updateHighlightState();
    }


    ngOnChanges(changes: SimpleChanges): void {
        if (this.globalSectionTemplates?.length > 0 && this.globalSectionTemplateFields?.length == 0) {
            this.initGlobalFieldsList();
            this.setSelectedGlobalTemplates();
        }
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

    private addRefSectionSelectionField(refSection: CmdbTypeSection): void {
        refSection.fields = [];
        refSection?.fields?.push(`${refSection?.name}-field`);

        this.typeInstance?.fields?.push({
            type: 'ref-section-field',
            name: `${refSection?.name}-field`,
            label: refSection?.label
        });

        this.typeInstance.fields = [...this.typeInstance?.fields];
    }


    private removeRefSectionSelectionField(refSection: CmdbTypeSection): void {
        const index = this.typeInstance?.fields?.map(x => x?.name).indexOf(`${refSection?.name}-field`);
        this.typeInstance?.fields?.splice(index, 1);
        this.typeInstance.fields = [...this.typeInstance?.fields];
    }


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

        event.event.preventDefault;
        let sectionData = event?.data;

        //check if it is a section template
        if ('is_global' in sectionData) {

            if (sectionData.is_global) {
                this.selectedGlobalSectionTemplates?.push(sectionData);

                let index = 0;
                for (let sectionIndex in this.globalSectionTemplates) {
                    const aTemplate = this.globalSectionTemplates[sectionIndex];

                    if (aTemplate?.name == sectionData?.name) {
                        index = parseInt(sectionIndex);
                        break;
                    }
                }

                this.globalSectionTemplates?.splice(index, 1);
                this.typeInstance?.global_template_ids?.push(sectionData?.name);
            }

            sectionData = this.extractSectionData(event?.data);
        }

        if (this.sections && (event?.dropEffect === 'copy' || event?.dropEffect === 'move')) {

            let index = event?.index;
            if (typeof index === 'undefined') {
                index = this.sections?.length;
            }

            for (const el of this.sections) {
                if (el.name && el?.name?.trim()) {
                    const collapseCard = this.el?.nativeElement?.querySelector(`#${el?.name}`);
                    if (collapseCard) {
                        this.renderer?.setStyle(collapseCard, 'display', 'none');
                    }
                }
            }

            if (event.dropEffect === 'copy') {
                this.newSections.push(sectionData);
            }

            if (event.dropEffect === 'move') {
                this.eventIndex = event?.index;
            }

            this.sections.splice(index, 0, sectionData);
            this.typeInstance.render_meta.sections = [...this.sections];
            this.sectionIdentifierService.getDroppedIndex(index);
            this.sectionIdentifierService.addSection(sectionData?.name, sectionData?.name, index);

            if (sectionData?.type === 'ref-section' && event?.dropEffect === 'copy') {
                this.addRefSectionSelectionField(sectionData as CmdbTypeSection);
            }

            //add fields of section template after the section was added
            if ('is_global' in event?.data) {
                this.setSectionTemplateFields(event?.data);
            }
        }

        this.validationService.setSectionValid(sectionData?.name, sectionData?.fields?.length > 0);
        this.updateSectionFieldStatus()
        this.updateHighlightState();
    }


    /**
     * This method checks if the field is used for an external link.
     * @param field
     */
    public externalField(field) {
        const include = { links: [], total: 0 };

        for (const external of this.typeInstance?.render_meta?.externals) {
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


    /**
     * Redirects changes to field properties
     * @param data new data for field
     */
    public onFieldChange(data: any, sectionIndex: number, fieldIndex: number) {
        if (data.hasOwnProperty("isDuplicate") && data?.isDuplicate) {

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
     * Sets and unsets a hidden field in the -ulti-data-ssection property 'hidden_fields'
     * 
     * @param data the new values which need to be processed
     */
    private handleHideFields(data: any) {
        let sectionIndex: number = this.getSectionOfField(data?.fieldName);
        let section: CmdbMultiDataSection = this.typeInstance?.render_meta?.sections[sectionIndex];

        if (!("hidden_fields" in section)) {
            section.hidden_fields = [];
        }

        if (data.newValue == true) {
            section.hidden_fields.push(data?.fieldName);
        } else {
            section.hidden_fields = section.hidden_fields.filter(hiddenField => hiddenField != data?.fieldName);
        }

        this.typeInstance.render_meta.sections[sectionIndex] = section;
    }


    /**
     * Updates the hidden_fields array of a section if the identifier was changed during the CREATE mode
     * 
     * @param previousName the identifier before the new value
     * @param newName the new value of the identifier
     */
    private updateHiddenFields(previousName: string, newName: string) {
        let sectionIndex: number = this.getSectionOfField(previousName);
        let section: CmdbMultiDataSection = this.typeInstance?.render_meta?.sections[sectionIndex];

        if (section?.hidden_fields?.includes(previousName)) {
            section.hidden_fields = section?.hidden_fields?.filter(hiddenField => hiddenField != previousName);
            section?.hidden_fields?.push(newName);
            this.typeInstance.render_meta.sections[sectionIndex] = section;
        }
    }


    public getFieldHiddenState(section: CmdbTypeSection | CmdbMultiDataSection, field: any): boolean {
        if (section.type == "multi-data-section") {
            if ((section as CmdbMultiDataSection)?.hidden_fields?.includes(field?.name)) {
                return true;
            } else {
                return false;
            }
        }

        return false;
    }

    private getSectionOfField(fieldName: string) {
        let index = 0;

        for (let aSection of this.typeInstance?.render_meta?.sections) {
            for (let aField of aSection?.fields) {
                if (aField.name == fieldName) {
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
     * @param data new data for field
     */
    private handleFieldChanges(data: any) {
        
        if (data.inputName === 'selectable_as_parent') {
            this.typeInstance.selectable_as_parent = !!data.newValue;
            return;
        }

        if (data.elementType == 'section') {
            this.validationService.updateSectionKey(data?.previousName, data?.fieldName)
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

            if (this.activeIndex !== null) {
                this.typeInstance.render_meta.sections[this.activeIndex][inputName] = newValue;
            }
            else if (index >= 0) {
                this.typeInstance.render_meta.sections[index][inputName] = newValue;
            }
        } else {
            if (data.inputName == "name") {
                this.updateHiddenFields(data?.previousName, data?.newValue);
            }

            index = this.getFieldIndexForName(fieldName);

            if (index >= 0) {
                this.typeInstance.fields[index][inputName] = newValue;
            }
        }

        this.refreshFieldIdentifiers();
        this.updateHighlightState();
    }


    /**
     * Retrieves the index of a field in the typeinstance
     * 
     * @param targetName name of the field which is searched
     * @returns (int): Index of the field. -1 of no field with this name is found
     */
    private getFieldIndexForName(targetName: string): number {
        return BuilderUtils?.getFieldIndexForName(this.typeInstance, targetName);
    }


    /**
     * Retrieves the index of a section in the typeinstance
     * 
     * @param targetName name of the field which is searched
     * @returns (int): Index of the field. -1 of no field with this name is found
     */
    private getSectionIndexForName(targetName: string): number {
        return BuilderUtils?.getSectionIndexForName(this.typeInstance, targetName);
    }

    /**
     * Handles the event when a field is dropped into a section. 
     * Updates the section field status, checks if the section is global, and processes the drop event.
     * Adds the dropped field data into the section and updates the type instance metadata.
     * @param event - The drop event, containing field data and drop effect.
     * @param section - The section where the field is dropped.
     */
    public onFieldDrop(event: DndDropEvent, section: CmdbTypeSection) {
        this.updateSectionFieldStatus()
        if (this.isGlobalSection(section)) {
            return;
        }

        const fieldData = event?.data;

        if (section && (event?.dropEffect === 'copy' || event?.dropEffect === 'move')) {
            let index = event?.index;

            this.initialIdentifier = section?.name;
            if (typeof index === 'undefined') {
                index = section?.fields?.length;
            }

            if (event.dropEffect === 'copy') {
                this.newFields?.push(fieldData);
            }

            section?.fields?.splice(index, 0, fieldData);
            this.typeInstance.render_meta.sections = [...this.sections];
            this.typeInstance.fields.push(fieldData);
            this.typeInstance.fields = [...this.typeInstance?.fields];
            this.validationService?.setSectionValid(section?.name, true);
        }
    }


    public onFieldDragged(item: any, section: CmdbTypeSection) {
        if (this.isGlobalSection(section)) {
            return;
        }

        const sectionIndex = section.fields.indexOf(item);
        section?.fields?.splice(sectionIndex, 1);
        const fieldIndex = this.typeInstance?.fields?.indexOf(item);
        let updatedDraggedFieldName = this.typeInstance?.fields[fieldIndex]?.name;

        this.typeInstance?.fields?.splice(fieldIndex, 1);
        this.typeInstance.fields = [...this.typeInstance?.fields];
        this.validationService?.setIsValid(updatedDraggedFieldName, true)

        this.refreshFieldIdentifiers();
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
            const index = list?.indexOf(item);
            list.splice(index, 1);
            this.sections = list;
            this.typeInstance.render_meta.sections = [...this.sections];
            this.sectionIdentifierService?.updateSectionIndexes(this.onSectionMoveIndex, this.eventIndex);
            this.updateHighlightState();
            this.refreshFieldIdentifiers();
        }
    }


    /**
     * Removes a section from the typeInstance and updates the relevant metadata and fields.
     *
     * @param item The section item to be removed.
     * @param sectionIndex The index of the section to be removed.
     */
    public removeSection(item: CmdbTypeSection, sectionIndex: number) {

        if (this.activeIndex === sectionIndex) {
            this.activeIndex = null
        }

        this.handleGlobalTemplates(item);
        this.sectionIdentifierService?.removeSection(sectionIndex);

        const index: number = this.typeInstance?.render_meta?.sections?.indexOf(item);

        if (index !== -1) {
            if (item.type === 'section') {
                const fields: Array<string> = this.typeInstance?.render_meta?.sections[index]?.fields;
                for (const field of fields) {
                    const fieldIdx = this.typeInstance?.fields.map(x => x?.name).indexOf(field['name']);
                    if (fieldIdx !== -1) {
                        this.typeInstance?.fields.splice(fieldIdx, 1);
                    }
                }

                this.typeInstance.fields = [...this.typeInstance?.fields];

            } else if (item.type === 'ref-section') {
                this.removeRefSectionSelectionField(item);
            }

            this.sections.splice(index, 1);
            this.typeInstance.render_meta.sections.splice(index, 1);
            this.typeInstance.render_meta.sections = [...this.typeInstance?.render_meta?.sections];

            this.updateHighlightState()
            this.refreshFieldIdentifiers()

            this.validationService.setSectionValid(item?.name, true);
        }
    }


    /**
     * Removes a field from the type instance and section, updates the validation state, and refreshes the UI.
     * @param item - The field item to be removed.
     * @param section - The section from which the field will be removed.
     */
    public removeField(item: any, section: CmdbTypeSection) {
        const indexField: number = this.typeInstance?.fields?.indexOf(item);

        if (indexField > -1) {
            let removedFieldName = this.typeInstance?.fields[indexField]?.name;
            this.typeInstance?.fields?.splice(indexField, 1);
            this.typeInstance.fields = [...this.typeInstance?.fields];
            this.validationService?.updateFieldValidityOnDeletion(removedFieldName);
        }

        const sectionFieldIndex = section?.fields?.indexOf(item);

        if (sectionFieldIndex > -1) {
            section?.fields?.splice(sectionFieldIndex, 1);
        }

        this.typeInstance.render_meta.sections = [...this.typeInstance?.render_meta.sections];

        let numberOfFields = section?.fields?.length > 0;

        if (!numberOfFields) {
            this.validationService?.setSectionValid(section?.name, false);
        }

        this.updateHighlightState()
        this.refreshFieldIdentifiers()
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
        const allSectionsHaveFields = this.sections?.every(section => section?.fields?.length > 0);

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
        const isDuplicateIdentifier = this.sections?.filter(s => s?.name === section?.name).length > 1;
        const isRefSection = section?.type === "ref-section";
        const hasInvalidFields = section?.fields?.some(field => this.isFieldHighlighted(field, section?.fields));

        // Check for section-level issues (name, label, duplicates)
        const hasSectionIssues = !section?.name || isDuplicateIdentifier || !section?.label;

        if (isRefSection) {
            const isInvalidReference = !section?.reference?.type_id || !section?.reference?.section_name;
            return isInvalidReference || hasSectionIssues;
        }

        // If the section has issues or any of its fields are invalid, highlight the section
        return hasSectionIssues || hasInvalidFields;
    }


    /**
     * Determines if a field should be highlighted based on its properties.
     * Checks for invalid identifiers, missing labels, and reference fields with invalid reference types.
     * @param field - The field to check for highlighting.
     * @param sectionfields - The list of all section fields for checking duplicate names.
     * @returns boolean - Returns true if the field should be highlighted, false otherwise.
     */
    public isFieldHighlighted(field: any, sectionfields: any): boolean {
        // Ensure field is a valid object (not null, undefined, or a primitive)
        if (!field || typeof field !== 'object') {
            return false;
        }
        const isRefField = field?.type === "ref";
        const hasInvalidIdentifier = !field?.name || sectionfields?.filter(s => s?.name === field?.name).length > 1;
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
     * Prevents drag events when any section is highlighted.
     * If a section is highlighted, this function stops the drag event while allowing other button interactions.
     * @param event - The drag event to be checked and possibly prevented.
     */
    public preventDragForAllSections(event: DragEvent): void {
        const isAnyHighlighted = this.sections?.some(section => this.isSectionHighlighted(section));
        if (isAnyHighlighted || this.disableFields) {
            event?.stopPropagation(); // Stops event from affecting other elements
            event?.preventDefault();  // Prevent dragging behavior
        }
    }


    /**
     * Prevents drag events for all fields within a section if any field in the section is highlighted.
     * @param event - The drag event to be checked and possibly prevented.
     * @param section - The section that contains the fields.
     */
    public preventDragForAllFields(event: DragEvent, section: any): void {
        // Check if any field in the section is highlighted (has an error)
        const isAnyFieldHighlighted = section?.fields?.some(field => this.isFieldHighlighted(field, section?.fields));
        const isAnyFieldEmpty = this.checkEmptyFields()?.length > 0;

        if (isAnyFieldHighlighted || isAnyFieldEmpty || this.disableFields) {
            event?.stopPropagation();  // Stops event from affecting other elements
            event?.preventDefault();   // Prevent dragging behavior
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
        this.validationService?.setSectionHighlightState(isSectionHighlighted);
        this.validationService?.setFieldHighlightState(isFieldHighlighted);
    }


    /**
     * Checks if any section is highlighted by evaluating the sections array.
     * @returns A boolean indicating if any section is currently highlighted.
     */
    isAnySectionHighlighted(): boolean {
        return this.sections?.some(section =>
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
            section?.fields?.some(field => this.isFieldHighlighted(field, section?.fields))
        );
    }


    /**
     * Checks for empty field names in each section and returns an array of objects 
     * containing the indices of sections and fields with empty or missing names.
     * @returns An array of objects with `sectionIndex` and `fieldIndex` for each field with an empty name.
     */
    checkEmptyFields(): Array<{ sectionIndex: number, fieldIndex: number }> {
        return this.sections?.flatMap((section, sectionIndex) =>
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
        if (emptyFields?.length === 0) {
            return false;
        }
        return !emptyFields?.some(emptyField => emptyField?.sectionIndex === sectionIndex && emptyField?.fieldIndex === fieldIndex);
    }


    /**
     * Refreshes the list of field identifiers by clearing existing field names
     * and adding the current field names from the type instance.
     */
    refreshFieldIdentifiers(): void {
        // this.fieldIdentifierValidation.clearFieldNames();
        // const fieldNames = this.typeInstance.fields.map(field => field.name);
        // this.fieldIdentifierValidation.addFieldNames(fieldNames);
        BuilderUtils.refreshFieldIdentifiers(this.typeInstance, this.fieldIdentifierValidation);

    }


    /**
     * Checks if the current section is locked based on empty fields.
     * If there are any empty fields, interactions are locked.
     * @returns {boolean} - Returns true if any fields are empty, otherwise false.
     */
    isLocked(): boolean {
        // Lock all interactions if there are any empty fields
        return this.checkEmptyFields()?.length > 0;
    }

    /* -------------------------------------------- SECTION TEMPLATE HANDLING ------------------------------------------- */

    public getDnDEffectAllowedForField(field: any) {
        return this.isGlobalField(field?.name) ? "none" : "move";
    }


    public getSectionMode(section: CmdbTypeSection, mode: CmdbMode) {
        //TODO: improve this condition
        if (this.isGlobalSection(section) || section?.name?.includes("dg_gst-") || section?.name?.includes("dg-")) {
            return CmdbMode.Global
        }

        if (this.isNewSection(section)) {
            return CmdbMode.Create
        }

        return mode;
    }


    /**
     * This prevents the special control "Location" to be placed inside an multi-data-section
     * 
     * @param sectionType 
     * @returns allowed types for a section
     */
    public getInputType(sectionType: string) {
        if (sectionType == "multi-data-section") {
            return ['inputs'];
        }

        return ['inputs', 'location'];

    }


    public getSectionCollapseIcon(section: CmdbTypeSection) {
        return this.isGlobalSection(section) ? ['far', 'eye'] : ['far', 'edit'];
    }


    public isGlobalSection(section: CmdbTypeSection) {
        for (let sectionIndex in this.globalSectionTemplates) {
            const aTemplate = this.globalSectionTemplates[sectionIndex];

            if (aTemplate?.name == section?.name) {
                return true;
            }
        }

        for (let sectionIndex in this.selectedGlobalSectionTemplates) {
            const aTemplate = this.selectedGlobalSectionTemplates[sectionIndex];

            if (aTemplate?.name == section?.name) {
                return true;
            }
        }

        return false;
    }


    public setSelectedGlobalTemplates() {
        if (this.typeInstance?.global_template_ids?.length > 0) {
            // iterate global_template_ids
            this.typeInstance?.global_template_ids?.forEach((globalTemplateName) => {

                let index: number = -1;

                for (let templateIndex in this.globalSectionTemplates) {
                    let aTemplate = this.globalSectionTemplates[templateIndex];

                    if (aTemplate?.name == globalTemplateName) {
                        this.selectedGlobalSectionTemplates?.push(aTemplate);
                        index = Number(templateIndex);
                    }
                }

                this.globalSectionTemplates?.splice(index, 1);
            })
        }
    }


    /**
     * Checks if the fieldName is in the List of global field names
     * 
     * @param fieldName Name of the field which should be checked
     * @returns True if it is in the List
     */
    public isGlobalField(fieldName: string) {
        return this.globalSectionTemplateFields?.indexOf(fieldName) > -1;
    }


    /**
     * Saves field names of all global section templates in a list
     */
    private initGlobalFieldsList() {

        for (let templateIndex in this.globalSectionTemplates) {
            let aTemplate = this.globalSectionTemplates[templateIndex];

            for (let fieldIndex in aTemplate?.fields) {
                let aField = aTemplate?.fields[fieldIndex];
                this.globalSectionTemplateFields?.push(aField.name);
            }
        }
    }


    private handleGlobalTemplates(sectionData: CmdbTypeSection) {
        let isGlobalTemplate = false;
        let globalTemplateIndex: number = -1;

        for (let index in this.selectedGlobalSectionTemplates) {
            const aSection = this.selectedGlobalSectionTemplates[index];
            if (aSection?.name == sectionData?.name) {
                isGlobalTemplate = true;
                globalTemplateIndex = parseInt(index);
                this.globalSectionTemplates?.push(aSection);
                this.globalSectionTemplates?.sort((a, b) => a?.public_id - b?.public_id);
            }
        }

        if (isGlobalTemplate) {
            const nameIndex = this.typeInstance?.global_template_ids?.indexOf(sectionData?.name, 0);
            this.typeInstance?.global_template_ids?.splice(nameIndex, 1);
            this.selectedGlobalSectionTemplates?.splice(globalTemplateIndex, 1);
        }
    }


    /**
     * 
     * @param data Extracts the section properties from the section template
     * @returns section properties
     */
    public extractSectionData(data: CmdbSectionTemplate) {
        let sectionName: string = data?.name;

        if (!data?.is_global && !this.isUniqueID(sectionName)) {
            sectionName = this.createUniqueID('section_template');
        }

        return {
            'name': sectionName,
            'label': data.label,
            'type': data.type,
            'fields': data.fields,
            'bg_color': '#ffffff'
        }
    }


    /**
     * Sets the fields from the section template to the type instance
     * @param sectionTemplateFields 
     */
    public setSectionTemplateFields(sectionTemplate: CmdbSectionTemplate) {
        let sectionTemplateFields = sectionTemplate?.fields;

        for (let fieldIndex in sectionTemplateFields) {
            let aField = sectionTemplateFields[fieldIndex];

            if (!this.isGlobalField(aField?.name) && !this.isUniqueID(aField?.name)) {
                aField.name = this.createUniqueID(aField?.type);
            }

            this.newFields?.push(aField);
            this.typeInstance?.fields?.push(aField);
        }

        this.typeInstance.fields = [...this.typeInstance.fields];
    }


    /**
     * Creates a unique name for section templates and fields if a section template is added more than once
     * @param name (string): The typ of the field or 'section_template'
     */
    public getUniqueName(name: string) {
        return this.createUniqueID(name);
    }


    /**
     * Creates a unique ID for a field or section
     * @param name (string): The name will be placed at the front of the ID
     */
    private createUniqueID(name: string) {
        const uniqueID = `${name}-${uuidv4()}`;

        // if ID is already used then create a new one
        if (this.isUniqueID(uniqueID)) {
            return uniqueID;
        } else {
            return this.createUniqueID(name);
        }
    }


    /**
     * Checks if the given ID already exists for a field or section
     * @param uniqueID THe given ID
     * @returns True if this ID is not used, else False
     */
    private isUniqueID(uniqueID: string) {
        //first check all field names
        for (let fieldIndex in this.typeInstance?.fields) {
            let currentField = this.typeInstance?.fields[fieldIndex];

            if (currentField?.name == uniqueID) {
                return false;
            }
        }

        //check all section names 
        for (let sectionIndex in this.typeInstance?.render_meta?.sections) {
            let currentSection = this.typeInstance?.render_meta?.sections[sectionIndex];

            if (currentSection?.name == uniqueID) {
                return false;
            }
        }

        return true;
    }


    /**
     * Sets the active index for the current section and updates the section identifier service.
     * @param index - The new active index to set.
     */
    setActiveIndex(index: number) {
        this.activeIndex = index;
        this.sectionIdentifierService?.setActiveIndex(index);
    }


    /**
     * Toggles the visibility of the color picker for the specified section.
     * @param section - The section for which the color picker visibility is toggled.
     */
    public toggleColorPicker(section: CmdbTypeSection): void {
        if (this.showColorPickerForSection === section?.name) {
            this.showColorPickerForSection = null;
        } else {
            this.showColorPickerForSection = section?.name;
        }
    }


    /**
     * Updates the background color of a specified section and applies it to the type instance metadata.
     * @param section - The section whose background color is to be updated.
     * @param color - The new color to set for the section.
     */
    public updateSectionColor(section: CmdbTypeSection, color: string): void {
        if (this.mode === this.MODES.View) {
            return;
        }

        // Validate color input, ensure it's a valid string
        if (!color || color?.trim() === '') {
            return;
        }

        section.bg_color = color;


        const sectionIndex = this.typeInstance?.render_meta?.sections?.findIndex((s) => s?.name === section?.name);
        if (sectionIndex !== -1) {
            this.typeInstance.render_meta.sections[sectionIndex].bg_color = color;
        }

        //hide the color picker after selecting a color
        // this.showColorPickerForSection = null;
    }

    /* ----------------------------------------------- CSS CLASS HANDLERS ------------------------------------------------ */


    /**
     * Returns the CSS classes for a section header based on its state.
     * Applies styles for global sections and highlighted headers.
     * @param section - The section to evaluate.
     */
    getSectionHeaderClass(section: any): any {
        return {
            'global-section-item': this.isGlobalSection(section),
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

    // public isNewSection(section: CmdbTypeSection): boolean {
    //     return this.newSections.indexOf(section) > -1;
    // }


    // public isNewField(field: any): boolean {
    //     return this.newFields.indexOf(field) > -1;
    // }


    // public openPreview() {
    //     const previewModal = this.modalService.open(PreviewModalComponent, { scrollable: true });
    //     previewModal.componentInstance.sections = this.sections;
    // }


    // public openDiagnostic() {
    //     const diagnosticModal = this.modalService.open(DiagnosticModalComponent, { scrollable: true });
    //     diagnosticModal.componentInstance.data = this.sections;
    // }


    // public matchedType(value: string) {
    //     switch (value) {
    //         case 'textarea':
    //             return 'align-left';
    //         case 'password':
    //             return 'key';
    //         case 'checkbox':
    //             return 'check-square';
    //         case 'radio':
    //             return 'check-circle';
    //         case 'select':
    //             return 'list';
    //         case 'ref':
    //             return 'retweet';
    //         case 'location':
    //             return 'globe';
    //         case 'date':
    //             return 'calendar-alt';
    //         default:
    //             return 'font';
    //     }
    // }

    /**
     * Checks if the given section is new by comparing it to the list of new sections.
     * @param section - The section to check.
     * @returns `true` if the section is new, otherwise `false`.
     */
    isNewSection(section: CmdbTypeSection): boolean {
        return BuilderUtils?.isNewSection(section, this.newSections);
    }


    /**
     * Checks if the given field is new by comparing it to the list of new fields.
     * @param field - The field to check.
     * @returns `true` if the field is new, otherwise `false`.
     */
    isNewField(field: any): boolean {
        return BuilderUtils?.isNewField(field, this.newFields);
    }


    /**
     * Opens a preview modal for the current sections.
     */
    openPreview(): void {
        BuilderUtils?.openPreview(this.modalService, this.sections);
    }


    /**
     * Opens a diagnostic modal for the current sections.
     */
    openDiagnostic(): void {
        BuilderUtils?.openDiagnostic(this.modalService, this.sections);
    }


    /**
     * Matches a given value to a corresponding type string.
     * @param value - The value to match.
     * @returns The matched type as a string.
     */
    matchedType(value: string): string {
        return BuilderUtils?.matchedType(value);
    }
}
