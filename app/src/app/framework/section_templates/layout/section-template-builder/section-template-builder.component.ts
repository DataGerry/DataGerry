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
import { Component, Input, OnInit, ViewChild } from '@angular/core';
import { FormControl, FormGroup } from '@angular/forms';
import { Router } from '@angular/router';

import { Observable } from 'rxjs';

import { v4 as uuidv4 } from 'uuid';
import { DndDropEvent } from 'ngx-drag-drop';

import { ValidationService } from 'src/app/framework/builder/services/validation.service';
import { SectionTemplateService } from '../../services/section-template.service';
import { ToastService } from 'src/app/layout/toast/toast.service';

import { CmdbMode } from 'src/app/framework/modes.enum';
import { Controller } from 'src/app/framework/builder/controls/controls.common';
import { APIInsertSingleResponse, APIUpdateSingleResponse } from 'src/app/services/models/api-response';
import { RenderResult } from 'src/app/framework/models/cmdb-render';
import { SectionFieldEditComponent } from 'src/app/framework/builder/configs/section/section-field-edit.component';
import { CheckboxControl } from 'src/app/framework/builder/controls/choice/checkbox.control';
import { RadioControl } from 'src/app/framework/builder/controls/choice/radio.control';
import { SelectControl } from 'src/app/framework/builder/controls/choice/select.control';
import { DateControl } from 'src/app/framework/builder/controls/date-time/date.control';
import { ReferenceControl } from 'src/app/framework/builder/controls/specials/ref.control';
import { PasswordControl } from 'src/app/framework/builder/controls/text/password.control';
import { TextControl } from 'src/app/framework/builder/controls/text/text.control';
import { TextAreaControl } from 'src/app/framework/builder/controls/text/textarea.control';
import { CmdbSectionTemplate } from 'src/app/framework/models/cmdb-section-template';
import { NumberControl } from 'src/app/framework/builder/controls/number/number.control';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'section-template-builder',
    templateUrl: './section-template-builder.component.html',
    styleUrls: ['./section-template-builder.component.scss'],
    standalone: false
})
export class SectionTemplateBuilderComponent implements OnInit {

    @Input()
    public sectionTemplateID: number;

    @ViewChild('sectionComponent')
    public sectionComponent: SectionFieldEditComponent;

    public initialSection: any = {
        'name': this.generateSectionTemplateName(),
        'label': 'Section',
        'type': 'section',
        'fields': []
    };

    public MODES: typeof CmdbMode = CmdbMode;
    public types = [];

    public formGroup: FormGroup;
    isNameValid = true;
    isLabelValid = true;
    isValid$: Observable<boolean>;

    public isFormValid: boolean = false;

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
        new Controller('ref', new ReferenceControl())
    ];

    /* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    constructor(
        private validationService: ValidationService,
        private sectionTemplateService: SectionTemplateService,
        private toastService: ToastService,
        private router: Router) {

        this.formGroup = new FormGroup({
            'isGlobal': new FormControl(false),
            'isMultiDataSection': new FormControl(false)
        });
    }


    ngOnInit(): void {
        //EDIT MODE
        if (this.sectionTemplateID > 0) {
            this.getSectionTemplate(this.sectionTemplateID);
        }

        this.isValid$ = this.validationService?.getIsValid();

        this.isValid$.subscribe(valid => {
            this.isFormValid = valid;
        });

        this.formGroup?.controls['isGlobal']?.valueChanges?.subscribe(isGlobal => {
            if (isGlobal) {
                if (this.initialSection?.name?.includes('dg_gst-')) {
                    this.sectionComponent?.form?.controls['name']?.setValue(this.initialSection?.name);
                } else {
                    this.sectionComponent.form?.controls['name']?.setValue(this.generateSectionTemplateName(isGlobal));
                }
            }
            else {
                if (this.initialSection?.name?.includes('section_template')) {
                    this.sectionComponent?.form?.controls['name']?.setValue(this.initialSection?.name);
                } else {
                    this.sectionComponent?.form?.controls['name']?.setValue(this.generateSectionTemplateName());
                }
            }
        });

        this.formGroup?.controls['isMultiDataSection']?.valueChanges?.subscribe(isMultiDataSection => {
            this.initialSection.type = isMultiDataSection ? 'multi-data-section' : 'section';
        });
    }

    public ngOnDestroy(): void {
        this.validationService?.cleanup();
    }

    /* ---------------------------------------------------- API Calls --------------------------------------------------- */

    /**
     * Decides if a section template should be crated or updated
     */
    public handleSectionTemplate() {

        if (this.initialSection.fields.length === 0 || !this.isFormValid) {
            this.toastService.error("Form is invalid or incomplete. Cannot save.");
            return;
        }

        this.initialSection.label = this.sectionComponent.form.controls['label'].value;
        this.initialSection.type = this.getSectionTemplateType();

        if (this.sectionTemplateID > 0) {
            this.updateSectionTemplate();
        } else {
            this.createSectionTemplate();
        }
    }


    /**
     * Send section template data to backend for creation
     */
    public createSectionTemplate() {
        let params = {
            "name": this.sectionComponent?.form?.controls['name']?.value,
            "label": this.initialSection?.label,
            "type": this.getSectionTemplateType(),
            "is_global": this.formGroup?.value?.isGlobal,
            "predefined": false,
            "fields": JSON.stringify(this.initialSection?.fields)
        }

        this.sectionTemplateService?.postSectionTemplate(params).subscribe({
            next: (res: APIInsertSingleResponse) => {
                this.toastService.success("Section Template created!");
                this.router.navigate(['/framework/section_templates']);
            },
            error: (error) => {
                this.toastService.error(error?.error?.message);
            }
        });
    }


    /**
     * Send section template data to backend to update the existing section template
     */
    public updateSectionTemplate() {
        let params = {
            'name': this.initialSection?.name,
            'label': this.initialSection?.label,
            'type': this.getSectionTemplateType(),
            'is_global': this.formGroup?.value?.isGlobal,
            'predefined': false,
            'fields': JSON.stringify(this.initialSection?.fields),
            'public_id': this.initialSection?.public_id
        }

        this.sectionTemplateService?.updateSectionTemplate(params)
            .subscribe({
                next: (res: APIUpdateSingleResponse) => {
                    this.toastService.success("Section Template updated!");
                    this.router.navigate(['/framework/section_templates']);
                },
                error: (error) => this.toastService.error(error?.error?.message)
            }
            );
    }


    /**
     * Retrieves a section template with the given publicID
     * 
     * @param publicID publicID of section template which should be edited
     */
    private getSectionTemplate(publicID: number) {
        this.sectionTemplateService?.getSectionTemplate(publicID)
            .subscribe({
                next: (response: CmdbSectionTemplate) => {
                    this.initialSection = response;
                    this.formGroup?.controls?.isGlobal?.setValue(this.initialSection?.is_global);
                    this.formGroup?.controls?.isMultiDataSection?.setValue(this.initialSection?.type === 'multi-data-section');
                },
                error: (error) => this.toastService.error(error?.error?.message)
            }
            );
    }

    /* ------------------------------------------------- EVENT HANDLERS ------------------------------------------------- */

    /**
     * Redirects changes to field properties
     * @param data new data for field
     */
    public onFieldChange(data: any) {
        this.handleFieldChanges(data);
    }


    /**
     * Handles changes to field properties and updates them
     * @param data new data for field
     */
    private handleFieldChanges(data: any) {
        const newValue: any = data.newValue;
        const inputName: string = data.inputName;
        const fieldName: string = data.fieldName;
        const index: number = this.getFieldIndexForName(fieldName);
        if (index >= 0) {
            this.initialSection.fields[index][inputName] = newValue;
        }
    }


    /**
     * Retrieves the index of a field in the typeinstance
     * 
     * @param targetName name of the field which is searched
     * @returns (int): Index of the field. -1 of no field with this name is found
     */
    private getFieldIndexForName(targetName: string): number {
        let index = 0;
        for (let field of this.initialSection?.fields) {

            if (field?.name == targetName) {
                return index;
            } else {
                index += 1;
            }
        }

        return -1;
    }


    /**
     * Handels dropping fields in Fieldzone
     * 
     * @param event triggered when a field is dropped in the Fieldszone
     */
    public onFieldDrop(event: DndDropEvent) {
        if (event.dropEffect === 'copy' || event.dropEffect === 'move') {
            this.initialSection?.fields?.splice(event?.index, 0, event?.data);
        }
    }


    /**
     * Checks if the field already exists in the section
     * 
     * @param field fieldData
     * @returns True if it a new field
     */
    public isNewField(field: any): boolean {
        return this.initialSection?.fields?.indexOf(field) > -1;
    }


    /**
     * Triggered when an existing field is moved inside the section
     * 
     * @param item field data
     */
    public onFieldDragged(item: any) {
        const fieldIndex = this.initialSection?.fields?.indexOf(item);
        let updatedDraggedFieldName = this.initialSection?.fields[fieldIndex]?.name;

        this.initialSection?.fields?.splice(fieldIndex, 1);
        this.validationService?.setIsValid(updatedDraggedFieldName, true)
    }


    /**
     * Triggered when a field is removed
     * 
     * @param item field which should be removed
     */
    public removeField(item: any) {
        const indexField: number = this.initialSection?.fields?.indexOf(item);
        let removedFieldName = this.initialSection?.fields[indexField]?.name;

        if (indexField > -1) {
            this.initialSection?.fields?.splice(indexField, 1);
            this.initialSection.fields = [...this.initialSection?.fields];
            this.validationService?.updateFieldValidityOnDeletion(removedFieldName);
        }
    }

    /* ------------------------------------------------- HELPER METHODS ------------------------------------------------- */

    /**
     * Sets the icon for the different controls
     * 
     * @param value string of field type
     * @returns Icon string
     */
    public matchedType(value: string) {
        switch (value) {
            case 'textarea':
                return 'align-left';
            case 'password':
                return 'key';
            case 'checkbox':
                return 'check-square';
            case 'radio':
                return 'check-circle';
            case 'select':
                return 'list';
            case 'ref':
                return 'retweet';
            case 'location':
                return 'globe';
            case 'date':
                return 'calendar-alt';
            default:
                return 'font';
        }
    }


    /**
     * Generates unique name for sections
     * 
     * @returns Unique name for section
     */
    public generateSectionTemplateName(isGlobal: boolean = false) {
        if (isGlobal) {
            return `dg_gst-${uuidv4()}`;
        }

        return `section_template-${uuidv4()}`;
    }


    private getSectionTemplateType(): string {
        return this.formGroup?.value?.isMultiDataSection ? 'multi-data-section' : 'section';
    }
}
