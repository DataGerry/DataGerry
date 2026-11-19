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
import { ChangeDetectionStrategy, Component, OnDestroy, OnInit, inject, signal } from '@angular/core';
import { AbstractControl, ReactiveFormsModule, UntypedFormControl, ValidationErrors, Validators } from '@angular/forms';
import { ReplaySubject } from 'rxjs';
import { takeUntil } from 'rxjs/operators';

import { NgbTooltipModule } from '@ng-bootstrap/ng-bootstrap';

import { CoreModule } from 'src/app/core/core.module';
import { LayoutModule } from 'src/app/layout/layout.module';
import { CopyService } from 'src/app/core/services/copy.service';
import { ValidationService } from 'src/app/framework/builder/services/validation.service';
import { FieldIdentifierValidationService } from 'src/app/framework/builder/services/field-identifier-validation.service';
import { reservedIdentifierPrefixValidator } from 'src/app/layout/validators/reserved-identifier-prefix-validator';

import { ConfigEditBaseComponent } from '../config.edit';
import { IdentifierHintComponent } from '../identifier-hint/identifier-hint.component';
import { PERSON_KINDS, PersonKind } from '../../../models/person-selector';
/* ------------------------------------------------------------------------------------------------------------------ */

const KIND_LABELS: Record<PersonKind, string> = {
    PERSON: 'Persons',
    PERSON_GROUP: 'Person groups'
};


function atLeastOneKind(control: AbstractControl): ValidationErrors | null {
    return Array.isArray(control.value) && control.value.length > 0 ? null : { noKind: true };
}


@Component({
    selector: 'cmdb-person-field-edit',
    templateUrl: './person-field-edit.component.html',
    changeDetection: ChangeDetectionStrategy.OnPush,
    imports: [ReactiveFormsModule, NgbTooltipModule, CoreModule, LayoutModule, IdentifierHintComponent]
})
export class PersonFieldEditComponent extends ConfigEditBaseComponent implements OnInit, OnDestroy {

    private static instances = 0;

    private readonly validationService = inject(ValidationService);
    private readonly fieldIdentifierValidation = inject(FieldIdentifierValidationService);
    private readonly copyService = inject(CopyService);

    protected subscriber: ReplaySubject<void> = new ReplaySubject<void>();

    public readonly controlId = `person-field-edit-${ ++PersonFieldEditComponent.instances }`;
    public readonly kinds = PERSON_KINDS;
    public readonly kindLabels = KIND_LABELS;

    public requiredControl = new UntypedFormControl(false);
    public nameControl = new UntypedFormControl('', [Validators.required, reservedIdentifierPrefixValidator()]);
    public labelControl = new UntypedFormControl('', Validators.required);
    public helperTextControl = new UntypedFormControl(undefined);
    public selectableControl = new UntypedFormControl(['PERSON'], atLeastOneKind);
    public multipleControl = new UntypedFormControl(false);

    public readonly isDuplicate = signal(false);

    private initialName: string;
    private identifierInitialValue: string;
    private priorName: string;

/* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    constructor() {
        super();
    }


    public ngOnInit(): void {
        this.form.addControl('required', this.requiredControl);
        this.form.addControl('name', this.nameControl);
        this.form.addControl('label', this.labelControl);
        this.form.addControl('helperText', this.helperTextControl);
        this.form.addControl('selectable', this.selectableControl);
        this.form.addControl('multiple', this.multipleControl);

        this.disableControlOnEdit(this.nameControl);
        this.patchData(this.data, this.form);

        this.initialName = this.nameControl.value;
        this.identifierInitialValue = this.nameControl.value;

        this.registerFieldChangeListeners();
        this.reportValidity();
    }


    public ngOnDestroy(): void {
        if (this.identifierInitialValue !== this.nameControl.value) {
            this.validationService.updateFieldValidityOnDeletion(this.identifierInitialValue);
        }

        this.subscriber.next();
        this.subscriber.complete();
    }

/* ---------------------------------------------------- EVENTS ------------------------------------------------------ */

    public onKindToggled(kind: PersonKind, checked: boolean): void {
        const current: PersonKind[] = this.selectableControl.value ?? [];
        const next = this.kinds.filter(entry => entry === kind ? checked : current.includes(entry));

        this.selectableControl.setValue(next);
        this.selectableControl.markAsTouched();
    }


    public onMultipleToggled(checked: boolean): void {
        this.multipleControl.setValue(checked);
    }

/* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    public isKindSelected(kind: PersonKind): boolean {
        return (this.selectableControl.value ?? []).includes(kind);
    }


    public async copyIdentifier(): Promise<void> {
        await this.copyService.copyWithFeedback(this.nameControl.value, 'person field identifier');
    }

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    private registerFieldChangeListeners(): void {
        const controls: Array<[UntypedFormControl, string]> = [
            [this.requiredControl, 'required'],
            [this.nameControl, 'name'],
            [this.labelControl, 'label'],
            [this.helperTextControl, 'helperText'],
            [this.selectableControl, 'selectable'],
            [this.multipleControl, 'multiple']
        ];

        for (const [control, inputName] of controls) {
            control.valueChanges
                .pipe(takeUntil(this.subscriber))
                .subscribe(value => this.onFieldChange(value, inputName));
        }
    }


    private onFieldChange(value: unknown, inputName: string): void {
        if (inputName === 'name' && !this.acceptName(value as string)) {
            return;
        }

        this.toggleOtherControls(false);

        if (inputName === 'name' && this.initialName !== value) {
            this.priorName = this.initialName;
        }

        this.fieldChanges$.next({
            newValue: value,
            inputName,
            fieldName: this.nameControl.value,
            previousName: this.initialName,
            elementType: 'person'
        });

        if (inputName === 'name') {
            this.initialName = this.nameControl.value;
        }

        this.reportValidity();
    }


    /** A duplicate identifier locks the other settings until it is made unique again. */
    private acceptName(name: string): boolean {
        const duplicate = this.fieldIdentifierValidation.isDuplicate(name) && name !== this.priorName;

        this.isDuplicate.set(duplicate);

        if (duplicate) {
            this.priorName = this.initialName;
            this.toggleOtherControls(true);
            this.fieldChanges$.next({ isDuplicate: true });
            this.validationService.setIsValid(this.identifierInitialValue, false);
        }

        return !duplicate;
    }


    private toggleOtherControls(disable: boolean): void {
        const controls = [
            this.requiredControl,
            this.labelControl,
            this.helperTextControl,
            this.selectableControl,
            this.multipleControl
        ];

        for (const control of controls) {
            if (disable) {
                control.disable({ emitEvent: false });
            } else if (!this.isReadOnly) {
                control.enable({ emitEvent: false });
            }
        }
    }


    private reportValidity(): void {
        const valid = this.nameControl.disabled
            ? this.labelControl.valid && this.selectableControl.valid
            : this.form.valid;

        this.validationService.setIsValid(this.identifierInitialValue, valid && !this.isDuplicate());
    }
}
