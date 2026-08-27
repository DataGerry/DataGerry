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
import { Component, OnDestroy, OnInit, SimpleChanges } from '@angular/core';
import { UntypedFormControl, Validators } from '@angular/forms';

import { ReplaySubject, Subscription } from 'rxjs';


import { ConfigEditBaseComponent } from '../config.edit';
import { CmdbMode } from 'src/app/framework/modes.enum';
import { SectionIdentifierService } from 'src/app/framework/builder/services/SectionIdentifierService.service';
import { ValidationService } from 'src/app/framework/builder/services/validation.service';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'cmdb-section-field-edit',
    host: { 'data-config-edit': 'relation' },
    templateUrl: './section-field-edit.component.html',
    standalone: false
})
export class SectionFieldEditComponent extends ConfigEditBaseComponent implements OnInit, OnDestroy {
    protected subscriber: ReplaySubject<void> = new ReplaySubject<void>();

    public nameControl: UntypedFormControl = new UntypedFormControl('', Validators.required);
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

    public constructor(private validationService: ValidationService, private sectionIdentifier: SectionIdentifierService) {
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
        this.fieldChanges$.next({
            "newValue": event,
            "inputName": type,
            "fieldName": this.nameControl.value,
            "previousName": this.initialValue,
            "elementType": "section",
        });

        if (type === "name") {
            const newName = this.nameControl.value;
            this.initialValue = newName;
        }

        setTimeout(() => {
            this.validationService.setIsValid(this.identifierInitialValue, this.isValid$);
            this.isValid$ = true;
        });

        if (this.mode === CmdbMode.Create) {
            this.updateSectionValue(this.nameControl.value)
        }
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
}