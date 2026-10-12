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
import { Component, OnDestroy, OnInit } from '@angular/core';
import { UntypedFormControl, Validators } from '@angular/forms';

import { ReplaySubject } from 'rxjs';
import { takeUntil } from 'rxjs/operators';

import { ValidationService } from 'src/app/framework/builder/services/validation.service';
import { FieldIdentifierValidationService } from 'src/app/framework/builder/services/field-identifier-validation.service';
import { CopyService } from '../../../../core/services/copy.service';
import { reservedIdentifierPrefixValidator } from '../../../../layout/validators/reserved-identifier-prefix-validator';

import { ConfigEditBaseComponent } from '../config.edit';
import { PERSON_FIELD_TYPE, PERSON_REF_KIND_OPTIONS, PersonRefKind } from '../../../models/person.model';
/* ------------------------------------------------------------------------------------------------------------------ */

/**
 * Config editor of the "Person / Person group selector": the usual identifier, label, description and
 * helper text, plus what the field may select (`person_ref_kind`) and whether it takes several objects
 * (`multiple`).
 */
@Component({
    selector: 'cmdb-person-field-edit',
    templateUrl: './person-field-edit.component.html',
    styleUrls: ['./person-field-edit.component.scss'],
    standalone: false
})
export class PersonFieldEditComponent extends ConfigEditBaseComponent implements OnInit, OnDestroy {

    protected subscriber: ReplaySubject<void> = new ReplaySubject<void>();

    public readonly refKindOptions = PERSON_REF_KIND_OPTIONS;

    public requiredControl: UntypedFormControl = new UntypedFormControl(false);
    public nameControl: UntypedFormControl = new UntypedFormControl('', [Validators.required, reservedIdentifierPrefixValidator()]);
    public labelControl: UntypedFormControl = new UntypedFormControl('', Validators.required);
    public descriptionControl: UntypedFormControl = new UntypedFormControl(undefined);
    public helperTextControl: UntypedFormControl = new UntypedFormControl(undefined);
    public refKindControl: UntypedFormControl = new UntypedFormControl(PersonRefKind.BOTH, Validators.required);
    public multipleControl: UntypedFormControl = new UntypedFormControl(false);

    private initialValue: string;
    private identifierInitialValue: string;
    private priorValue: string | boolean;
    public isValid$: boolean = false;
    public isDuplicate$: boolean = false;

    /* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    constructor(
        private validationService: ValidationService,
        private fieldIdentifierValidation: FieldIdentifierValidationService,
        private copyService: CopyService
    ) {
        super();
    }


    public ngOnInit(): void {
        this.form.addControl('required', this.requiredControl);
        this.form.addControl('name', this.nameControl);
        this.form.addControl('label', this.labelControl);
        this.form.addControl('description', this.descriptionControl);
        this.form.addControl('helperText', this.helperTextControl);
        this.form.addControl('person_ref_kind', this.refKindControl);
        this.form.addControl('multiple', this.multipleControl);

        // A field written before the keys existed falls back to the backend defaults
        if (this.data) {
            this.data.person_ref_kind = this.data.person_ref_kind ?? PersonRefKind.BOTH;
            this.data.multiple = !!this.data.multiple;
        }

        this.disableControlOnEdit(this.nameControl);
        this.patchData(this.data, this.form);

        this.initialValue = this.nameControl.value;
        this.identifierInitialValue = this.nameControl.value;

        this.registerFieldChangeListeners();

        this.isValid$ = this.form.valid;
        this.form.statusChanges.pipe(takeUntil(this.subscriber)).subscribe(() => {
            this.isValid$ = this.form.valid;
        });
    }


    public ngOnDestroy(): void {
        // When moving a field, if the identifier changes, delete the old one and add the new one.
        if (this.identifierInitialValue != this.nameControl.value) {
            this.validationService.updateFieldValidityOnDeletion(this.identifierInitialValue);
        }

        this.subscriber?.next();
        this.subscriber?.complete();
    }

    /* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    /**
     * Propagates one control's change to the field, refusing a duplicate identifier the way the other
     * field editors do.
     */
    public onInputChange(event: any, type: string): void {
        if (typeof event === 'boolean') {
            this.handleFieldChange(event, type);
            return;
        }

        if (type === 'name') {
            this.isDuplicate$ = this.fieldIdentifierValidation.isDuplicate(event);

            if (!this.isDuplicate$) {
                this.toggleFormControls(false);
                this.handleFieldChange(event, type);
            } else if (event === this.priorValue) {
                this.isDuplicate$ = false;
                this.toggleFormControls(false);
                this.handleFieldChange(event, type);
            } else {
                this.priorValue = this.initialValue;
                this.toggleFormControls(true);
                this.fieldChanges$.next({ 'isDuplicate': true });
            }
        } else {
            this.toggleFormControls(false);
            this.handleFieldChange(event, type);
        }

        setTimeout(() => {
            this.validationService.setIsValid(this.identifierInitialValue, this.isValid$);
            this.isValid$ = true;
        });
    }


    public async copyIdentifier(): Promise<void> {
        await this.copyService.copyWithFeedback(this.nameControl.value, 'person field identifier');
    }

    /* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    private handleFieldChange(event: any, type: string): void {
        if (type === 'name' && this.initialValue !== event) {
            this.priorValue = this.initialValue;
        }

        this.fieldChanges$.next({
            'newValue': event,
            'inputName': type,
            'fieldName': this.nameControl.value,
            'previousName': this.initialValue,
            'elementType': PERSON_FIELD_TYPE
        });

        if (type === 'name') {
            this.initialValue = this.nameControl.value;
        }
    }


    private registerFieldChangeListeners(): void {
        const controls: Array<[UntypedFormControl, string]> = [
            [this.nameControl, 'name'],
            [this.labelControl, 'label'],
            [this.descriptionControl, 'description'],
            [this.helperTextControl, 'helperText'],
            [this.requiredControl, 'required'],
            [this.refKindControl, 'person_ref_kind'],
            [this.multipleControl, 'multiple']
        ];

        controls.forEach(([control, type]) => {
            control.valueChanges
                .pipe(takeUntil(this.subscriber))
                .subscribe(value => this.onInputChange(value, type));
        });
    }


    /** `emitEvent: false` keeps these programmatic toggles from re-triggering the value change listeners. */
    private toggleFormControls(disable: boolean): void {
        const controls = [
            this.labelControl,
            this.descriptionControl,
            this.helperTextControl,
            this.requiredControl,
            this.refKindControl,
            this.multipleControl
        ];

        controls.forEach(control => disable
            ? control.disable({ emitEvent: false })
            : control.enable({ emitEvent: false })
        );
    }
}
