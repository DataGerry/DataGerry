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
* along with this program.  If not, see <https://www.gnu.org/licenses/>.
*/
import { Component, OnChanges, OnDestroy, OnInit, SimpleChanges } from '@angular/core';
import { UntypedFormControl, Validators } from '@angular/forms';
import { reservedIdentifierPrefixValidator } from '../../../../layout/validators/reserved-identifier-prefix-validator';

import { ReplaySubject, Subscription } from 'rxjs';

import { ValidationService } from 'src/app/framework/builder/services/validation.service';

import { ConfigEditBaseComponent } from '../config.edit';
import { SectionIdentifierService } from 'src/app/framework/builder/services/SectionIdentifierService.service';
import { CmdbMode } from 'src/app/framework/modes.enum';
import { CopyService } from '../../../../core/services/copy.service';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'cmdb-section-field-edit',
    templateUrl: './section-field-edit.component.html',
    standalone: false
})
export class SectionFieldEditComponent extends ConfigEditBaseComponent implements OnInit, OnChanges, OnDestroy {
    protected subscriber: ReplaySubject<void> = new ReplaySubject<void>();

    public nameControl: UntypedFormControl = new UntypedFormControl('', [Validators.required, reservedIdentifierPrefixValidator()]);
    public labelControl: UntypedFormControl = new UntypedFormControl('', Validators.required);

    private initialValue: string;
    private identifierInitialValue: string;
    isValid$: boolean = false;
    public currentValue: string;
    public isIdentifierValid: boolean = true;
    private activeIndex: number | null = null;
    private activeIndexSubscription: Subscription;

    /* ------------------------------------------------------------------------------------------------------------------ */
    /*                                                     LIFE CYCLE                                                     */
    /* ------------------------------------------------------------------------------------------------------------------ */

    public constructor(
        private validationService: ValidationService, 
        private sectionIdentifier: SectionIdentifierService,
        private copyService: CopyService
    ) {
        super();
    }

    public ngOnInit(): void {
        this.form.addControl('name', this.nameControl);
        this.form.addControl('label', this.labelControl);

        this.disableControlOnEdit(this.nameControl);
        this.disableControlsOnGlobal(this.nameControl);
        this.disableControlsOnGlobal(this.labelControl);
        this.patchData(this.data, this.form);
        this.initialValue = this.nameControl.value;
        this.identifierInitialValue = this.nameControl.value;
        this.currentValue = this.identifierInitialValue;

        // Subscribe to value changes
        this.nameControl.valueChanges.subscribe(value => this.onInputChange(value, 'name'));
        this.labelControl.valueChanges.subscribe(value => this.onInputChange(value, 'label'));

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
        if (this.activeIndexSubscription) {
            this.activeIndexSubscription.unsubscribe();
        }
    }


    public ngOnChanges(changes: SimpleChanges): void {
        if (changes.data && !changes.data.firstChange) {
            this.updateFormControls(changes.data.currentValue);
        }
    }

    /* ------------------------------------------------- HELPER METHODS ------------------------------------------------- */



    /**
     * Handles input changes for the field and emits changes through fieldChanges$.
     * Updates the initial value if the input type is 'name' and triggers validation after a delay.
     * @param event - The input event value.
     * @param type - The type of the input field being changed.
     */
    onInputChange(event: any, type: string) {
        const elementType = this.elementType;
        const isMultiDataSection = elementType === 'multi-data-section';
        const isDuplicateName = type === 'name' && this.isDuplicateSectionIdentifier(event);

        if (type === 'name') {
            this.setDuplicateIdentifierState(isDuplicateName);
        }

        // A multi-data-section reports the duplicate and stops; a plain section reports the value
        // change first and flags the duplicate after. Both flows are kept as they were - which of
        // the two is correct is a behaviour question, not a de-duplication one.
        if (isMultiDataSection && type === 'name' && isDuplicateName) {
            this.validationService.setSectionHighlightState(true);
            this.fieldChanges$.next({ isDuplicate: true, elementType });

            return;
        }

        if (isMultiDataSection && type === 'name') {
            this.fieldChanges$.next({ isDuplicate: false, elementType });
        }

        this.fieldChanges$.next({
            "newValue": event,
            "inputName": type,
            "fieldName": this.nameControl.value,
            "previousName": this.initialValue,
            "elementType": elementType,
        });

        if (type === "name") {
            this.initialValue = this.nameControl.value;

            if (!isMultiDataSection) {
                if (isDuplicateName) {
                    this.validationService.setSectionHighlightState(true);
                }
                this.fieldChanges$.next({ isDuplicate: isDuplicateName, elementType });
            }
        }

        setTimeout(() => {
            this.validationService.setIsValid(this.identifierInitialValue, this.isValid$);
            this.isValid$ = true;
        });

        // The multi-data-section variant has always synced unconditionally.
        if (isMultiDataSection || this.mode === CmdbMode.Create) {
            this.updateSectionValue(this.nameControl.value)
        }
    }


    /** Section flavour this editor is rendering, taken from the bound section's own type. */
    private get elementType(): 'section' | 'multi-data-section' {
        return this.data?.type === 'multi-data-section' ? 'multi-data-section' : 'section';
    }


    private isDuplicateSectionIdentifier(newValue: string): boolean {
        if (!newValue || newValue === this.currentValue) {
            return false;
        }

        return (this.sections ?? []).some(section => section !== this.data && section?.name === newValue);
    }


    private setDuplicateIdentifierState(isDuplicate: boolean): void {
        this.isIdentifierValid = !isDuplicate;
        const errors = { ...(this.nameControl.errors ?? {}) };

        if (isDuplicate) {
            this.nameControl.setErrors({ ...errors, duplicateIdentifier: true });
            return;
        }

        delete errors.duplicateIdentifier;
        this.nameControl.setErrors(Object.keys(errors).length ? errors : null);
    }


    /**
     * Updates the section value based on the provided new value.
     * Validates the section identifier and updates the identifier validity state.
     * @param newValue - The new value for the section.
     */
    updateSectionValue(newValue: string): void {

        // Subscribe to getActiveIndex only once and store the latest index
        this.activeIndexSubscription = this.sectionIdentifier.getActiveIndex().subscribe((index) => {
            if (index !== null && index !== undefined) {
                this.activeIndex = index;  // Update the latest active index
            }
        });

        setTimeout(() => {
            if (newValue === this.currentValue) {
                return;
            }

            const isValid = this.sectionIdentifier.updateSection(this.activeIndex, newValue);

            if (!isValid) {
                this.isIdentifierValid = false;
            } else {
                this.currentValue = newValue;
                this.isIdentifierValid = true;
            }
        }, 200);
    }


    /**
     * Updates form controls with new data.
     * @param newData - The new data object to patch into the form.
     */
    private updateFormControls(newData: any) {
        if (newData) {
            this.form.patchValue({
                label: newData.label,
                name: newData.name
            });
        }
    }

    /**
     * Copies the current field identifier to clipboard
     */
    public async copyIdentifier(): Promise<void> {
        const label = this.elementType === 'multi-data-section'
            ? 'multi-data section identifier'
            : 'section field identifier';

        await this.copyService.copyWithFeedback(this.nameControl.value, label);
    }
}
