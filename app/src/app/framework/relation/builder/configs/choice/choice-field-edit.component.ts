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
import { Component, OnInit } from '@angular/core';
import { UntypedFormControl, Validators } from '@angular/forms';

import { ReplaySubject } from 'rxjs';


import { ConfigEditBaseComponent } from '../config.edit';
import { ValidationService } from 'src/app/framework/type/services/validation.service';
import { FieldIdentifierValidationService } from 'src/app/framework/type/services/field-identifier-validation.service';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'cmdb-choice-field-edit',
    templateUrl: './choice-field-edit.component.html',
    styleUrls: ['./choice-field-edit.component.scss'],
    standalone: false
})
export class ChoiceFieldEditComponent extends ConfigEditBaseComponent implements OnInit {

    protected subscriber: ReplaySubject<void> = new ReplaySubject<void>();

    public requiredControl: UntypedFormControl = new UntypedFormControl(false);
    public nameControl: UntypedFormControl = new UntypedFormControl('', Validators.required);
    public labelControl: UntypedFormControl = new UntypedFormControl('', Validators.required);
    public descriptionControl: UntypedFormControl = new UntypedFormControl('');
    public helperTextControl: UntypedFormControl = new UntypedFormControl('');
    public optionsControl: UntypedFormControl = new UntypedFormControl([]);
    public valueControl: UntypedFormControl = new UntypedFormControl();
    public hideFieldControl: UntypedFormControl = new UntypedFormControl(false);

    // Add able options for choice selection
    public options: Array<any> = [];

    private initialValue: string;
    isValid$: boolean = false;
    private identifierInitialValue: string;
    private priorValue: string | boolean; // To store the value before the previous change
    isDuplicate$: boolean = false

    /* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    constructor(private validationService: ValidationService, private fieldIdentifierValidation: FieldIdentifierValidationService) {
        super();
    }


    public ngOnInit(): void {
        this.options = this.data.options;

        if (this.options === undefined || !Array.isArray(this.options)) {
            this.options = [];
            this.options.push({
                name: `option-${(this.options.length + 1)}`,
                label: `Option ${(this.options.length + 1)}`
            });
            this.data.options = this.options;
        }

        this.form.addControl('required', this.requiredControl);
        this.form.addControl('name', this.nameControl);
        this.form.addControl('label', this.labelControl);
        this.form.addControl('description', this.descriptionControl);
        this.form.addControl('helperText', this.helperTextControl);
        this.form.addControl('value', this.valueControl);
        this.form.addControl('options', this.optionsControl);
        this.form.addControl('hideField', this.hideFieldControl);

        this.disableControlOnEdit(this.nameControl);
        this.patchData(this.data, this.form);

        this.initialValue = this.nameControl.value;
        this.identifierInitialValue = this.nameControl.value;

        if (this.hiddenStatus) {
            this.hideFieldControl.setValue(true);
        }

        // Initialize only once
        if (!this.identifierInitialValue) {
            this.identifierInitialValue = this.nameControl.value;
        }

        this.isValid$ = this.form.valid;

        // Subscribe to form status changes and update isValid$ based on form validity
        this.form.statusChanges.subscribe(() => {
            this.isValid$ = this.form.valid;
        });
    }


    public ngOnDestroy(): void {
        //   When moving a field, if the identifier changes, delete the old one and add the new one.
        if (this.identifierInitialValue != this.nameControl.value) {
            this.validationService.updateFieldValidityOnDeletion(this.identifierInitialValue);
        }
        this.subscriber?.next();
        this.subscriber?.complete();
    }

    /* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    /**
     * Adds a new option with default prefix
     */
    public addOption(): void {
        this.options.push({
            name: `option-${(this.options.length + 1)}`,
            label: `Option ${(this.options.length + 1)}`
        });
    }


    /**
     * Deletes a existing option.
     * @param value
     */
    public delOption(value: any): void {

        if (this.options.length > 1) {
            const index = this.options.indexOf(value, 0);

            if (index > -1) {
                this.options.splice(index, 1);
            }
        }
    }


    // /**
    //  * Handles input changes for the field and emits changes through fieldChanges$.
    //  * Updates the initial value if the input type is 'name' and triggers validation after a delay.
    //  * @param event - The input event value.
    //  * @param type - The type of the input field being changed.
    //  */
    // onInputChange(event: any, type: string) {
    //     console.log('choice', event)
    //     this.fieldChanges$.next({
    //         "newValue": event,
    //         "inputName": type,
    //         "fieldName": this.nameControl.value,
    //         "previousName": this.initialValue,
    //         "elementType": "choise"
    //     });

    //     if (type == "name") {
    //         this.initialValue = this.nameControl.value;
    //     }

    //     setTimeout(() => {
    //         this.validationService.setIsValid(this.identifierInitialValue, this.isValid$);
    //         this.isValid$ = true;
    //     });
    // }

    /**
     * Handles input changes for the field and emits changes through fieldChanges$.
     * Updates the initial value if the input type is 'name' and triggers validation after a delay.
     * @param event - The input event value.
     * @param type - The type of the input field being changed.
     */
    onInputChange(event: any, type: string) {
        // Handle boolean event type
        if (typeof event === 'boolean') {
            this.handleFieldChange(event, type);
            return;
        }

        if (type === 'name') {
            // Check for duplicates
            this.isDuplicate$ = this.fieldIdentifierValidation.isDuplicate(event);

            if (!this.isDuplicate$) {
                this.toggleFormControls(false);
                this.handleFieldChange(event, type);
            }
            else if (event === this.priorValue) {
                this.isDuplicate$ = false
                this.toggleFormControls(false);
                this.handleFieldChange(event, type);
            }
            else {
                this.priorValue = this.initialValue
                this.toggleFormControls(true);
                this.fieldChanges$.next({ "isDuplicate": true });
            }
        } else {
            this.toggleFormControls(false);
            this.handleFieldChange(event, type);
        }

        // Perform validation after a slight delay
        setTimeout(() => {
            this.validationService.setIsValid(this.identifierInitialValue, this.isValid$);
            this.isValid$ = true;
        });
    }


    /**
     * Handles changes to the form fields and notifies listeners of the change event.
     * Updates the initial value if the field type is 'name' and triggers field change notifications.
     * @param event - The new value of the field after change.
     * @param type - The type of field being changed (e.g., 'name').
     */
    private handleFieldChange(event: any, type: string): void {
        // Update previousPreviousValue before changing the initialValue
        if (type === 'name' && this.initialValue !== event) {
            this.priorValue = this.initialValue;
        }

        // Notify field changes
        this.fieldChanges$.next({
            "newValue": event,
            "inputName": type,
            "fieldName": this.nameControl.value,
            "previousName": this.initialValue,
            "elementType": "choise"
        });

        // Update the initial value if the type is 'name'
        if (type === 'name') {
            this.initialValue = this.nameControl.value;
        }
    }


    /**
     * Toggles the enabled or disabled state of the form controls based on the `disable` parameter.
     * If `disable` is true, the form controls are disabled; otherwise, they are enabled.
     * @param disable - A boolean value determining whether to disable or enable the form controls.
     */
    private toggleFormControls(disable: boolean) {
        // Disable or enable form controls based on the value of `disable`
        if (disable) {
            this.labelControl.disable();
            this.descriptionControl.disable();
            this.valueControl.disable();
            this.helperTextControl.disable();
            this.hideFieldControl.disable();
            this.requiredControl.disable();
            this.optionsControl.disable();
        } else {
            this.labelControl.enable();
            this.descriptionControl.enable();
            this.valueControl.enable();
            this.helperTextControl.enable();
            this.hideFieldControl.enable();
            this.requiredControl.enable();
            this.optionsControl.enable();
        }
    }
}
