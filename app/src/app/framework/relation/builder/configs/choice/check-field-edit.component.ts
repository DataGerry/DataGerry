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
import { Component, OnInit } from '@angular/core';
import { UntypedFormControl, Validators } from '@angular/forms';

import { ReplaySubject } from 'rxjs';


import { ConfigEditBaseComponent } from '../config.edit';
import { FieldIdentifierValidationService } from 'src/app/framework/type/services/field-identifier-validation.service';
import { ValidationService } from 'src/app/framework/type/services/validation.service';
/* ------------------------------------------------------------------------------------------------------------------ */
@Component({
    selector: 'cmdb-check-field-edit',
    templateUrl: './check-field-edit.component.html',
    styleUrls: ['./check-field-edit.component.scss'],
    standalone: false
})
export class CheckFieldEditComponent extends ConfigEditBaseComponent implements OnInit {

    // Component un-subscriber
    protected subscriber: ReplaySubject<void> = new ReplaySubject<void>();

    public nameControl: UntypedFormControl = new UntypedFormControl('', Validators.required);
    public labelControl: UntypedFormControl = new UntypedFormControl('', Validators.required);
    public descriptionControl: UntypedFormControl = new UntypedFormControl('');
    public valueControl: UntypedFormControl = new UntypedFormControl(false);
    public helperTextControl: UntypedFormControl = new UntypedFormControl('');
    public hideFieldControl: UntypedFormControl = new UntypedFormControl(false);

    private initialValue: string;
    isValid$: boolean = false;
    private identifierInitialValue: string;
    private priorValue: string | boolean; // To store the value before the previous change

    isDuplicate$: boolean = false;

    /* ------------------------------------------------------------------------------------------------------------------ */
    /*                                                     LIFE CYCLE                                                     */
    /* ------------------------------------------------------------------------------------------------------------------ */

    constructor(private validationService: ValidationService, private fieldIdentifierValidation: FieldIdentifierValidationService) {
        super();
    }


    public ngOnInit(): void {
        this.data.options = [{
            name: 'option-1',
            label: 'Option 1'
        }];

        this.form.addControl('name', this.nameControl);
        this.form.addControl('label', this.labelControl);
        this.form.addControl('description', this.descriptionControl);
        this.form.addControl('value', this.valueControl);
        this.form.addControl('helperText', this.helperTextControl);
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
            "elementType": "checkbox"
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
        } else {
            this.labelControl.enable();
            this.descriptionControl.enable();
            this.valueControl.enable();
            this.helperTextControl.enable();
            this.hideFieldControl.enable();
        }
    }
}
