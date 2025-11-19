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

* You should have received a copy of the GNU Affero General Public License
* along with this program. If not, see <https://www.gnu.org/licenses/>.
*/

import { Component, OnDestroy, OnInit } from '@angular/core';
import { ConfigEditBaseComponent } from '../config.edit';
import { CmdbType, CmdbTypeSection } from '../../../../models/cmdb-type';
import { CollectionParameters } from '../../../../../services/models/api-parameter';
import { TypeService } from '../../../../services/type.service';
import { takeUntil } from 'rxjs/operators';
import { APIGetMultiResponse } from '../../../../../services/models/api-response';
import { ReplaySubject, Subscription } from 'rxjs';
import { CmdbMode } from '../../../../modes.enum';
import { UntypedFormControl, UntypedFormGroup, Validators } from '@angular/forms';
import { ToastService } from "../../../../../layout/toast/toast.service";
import { ValidationService } from '../../../services/validation.service';
import { SectionIdentifierService } from '../../../services/SectionIdentifierService.service';
import { CopyService } from '../../../../../core/services/copy.service';

@Component({
    selector: 'cmdb-section-ref-field-edit',
    templateUrl: './section-ref-field-edit.component.html',
    standalone: false
})
export class SectionRefFieldEditComponent extends ConfigEditBaseComponent implements OnInit, OnDestroy {

    /**
     * Component un-subscriber.
     * @protected
     */
    protected subscriber: ReplaySubject<void> = new ReplaySubject<void>();

    /**
     * Name form control.
     */
    public nameControl: UntypedFormControl = new UntypedFormControl('', Validators.required);

    /**
     * Label form control.
     */
    public labelControl: UntypedFormControl = new UntypedFormControl('', Validators.required);

    /**
     * Type form control.
     */
    public typeControl: UntypedFormControl = new UntypedFormControl(undefined, Validators.required);

    /**
     * Type form control.
     */
    public sectionNameControl: UntypedFormControl = new UntypedFormControl(undefined, Validators.required);

    /**
     * Type form control.
     */
    public selectedFieldsControl: UntypedFormControl = new UntypedFormControl([]);

    /**
     * Reference form control.
     */
    public referenceGroup: UntypedFormGroup = new UntypedFormGroup({
        type_id: this.typeControl,
        section_name: this.sectionNameControl,
        selected_fields: this.selectedFieldsControl
    });

    /**
     * Sections from the selected type.
     */
    public typeSections: Array<CmdbTypeSection> = [];

    /**
     * Selected section
     */
    public selectedSection: CmdbTypeSection;

    /**
     * Types load right now?
     */
    public loading: boolean = false;

    /**
     * Total number of types.
     */
    public totalTypes: number = 0;

    /**
     * Current loading page
     */
    public currentPage: number = 1;

    /**
     * Max loading pages.
     * @private
     */
    private maxPage: number = 1;

    /**
     * Type switch active.
     */
    public selectDisabled: boolean = false;

    private previousNameControlValue: string = '';
    private initialValue: string;

    public currentValue: string;
    public isIdentifierValid: boolean = true;
    private identifierInitialValue: string;
    private activeIndex: number | null = null;
    private activeIndexSubscription: Subscription;
    public isValid$ = false;

    constructor(private typeService: TypeService, private toast: ToastService, private validationService: ValidationService,
        private sectionIdentifier: SectionIdentifierService, private copyService: CopyService) {
        super();
    }

    /**
     * Generate the type call parameters
     * @param page
     * @private
     */
    static getApiParameters(page: number = 1): CollectionParameters {
        return {
            filter: undefined, limit: 10, sort: 'public_id',
            order: 1, page
        } as CollectionParameters;
    }

    public ngOnInit(): void {
        this.form.addControl('name', this.nameControl);
        this.form.addControl('label', this.labelControl);
        this.form.addControl('reference', this.referenceGroup);

        if (this.mode === CmdbMode.Edit || this.mode === CmdbMode.Create) {
            if (this.data?.reference?.type_id) {
                this.loadPresetType(this.data.reference.type_id);
            }
        }

        this.disableControlOnEdit(this.nameControl);
        this.patchData(this.data, this.form);

        this.triggerAPICall();

        this.initialValue = this.nameControl.value;
        this.previousNameControlValue = this.nameControl.value;

        this.currentValue = this.identifierInitialValue;

        this.nameControl.valueChanges.subscribe(value => this.onNameChange(value));
        this.labelControl.valueChanges.subscribe(value => this.onLabelChange(value, 'label'));

        this.isValid$ = this.form.valid;

        // Subscribe to form status changes and update isValid$ based on form validity
        this.form.statusChanges.subscribe(() => {
            this.isValid$ = this.form.valid;
            this.validationService.setIsValid(this.initialValue, this.isValid$);

        });
    }

    private loadPresetType(publicID: number): void {
        this.loading = true;
        this.typeService.getType(publicID).pipe(takeUntil(this.subscriber))
            .subscribe({
                next: (apiResponse: CmdbType) => {
                    this.typeSections = apiResponse.render_meta.sections;
                    this.selectedSection = this.typeSections.find(s => s.name === this.data.reference.section_name);
                },
                error: (error) =>
                    this.toast.error(error.error.message, { headerName: 'Field error: ' + this.nameControl.value })
            })
            .add(() => this.loading = false);
    }

    public triggerAPICall(): void {
        if (this.maxPage && (this.currentPage <= this.maxPage)) {
            this.loadTypesFromApi();
            this.currentPage += 1;
        }
    }

    private loadTypesFromApi(): void {
        this.loading = true;
        this.typeService.getTypes(SectionRefFieldEditComponent.getApiParameters(this.currentPage)).pipe(takeUntil(this.subscriber))
            .subscribe((apiResponse: APIGetMultiResponse<CmdbType>) => {
                this.types = [...this.types, ...apiResponse.results as Array<CmdbType>];
                this.totalTypes = apiResponse.total;
                this.maxPage = apiResponse.pager.total_pages;
            }).add(() => this.loading = false);
    }

    /**
     * When the selected type change.
     * Reset a selected section.
     * @param publicID
     */
    public onTypeChange(publicID: number): void {
        if (publicID) {
            this.data.reference.type_id = publicID;
            this.typeSections = this.getSectionsFromType(publicID);
        } else {
            this.data.reference.type_id = undefined;
            this.typeSections = [];
        }
        this.unsetReferenceSubData();
    }

    private unsetReferenceSubData(): void {
        this.data.reference.section_name = undefined;
        this.sectionNameControl.setValue(undefined);
        this.data.reference.selected_fields = undefined;
        this.selectedFieldsControl.setValue(undefined);
        this.selectedSection = undefined;
    }

    /**
     * Get all sections from a type.
     * @param typeID
     */
    public getSectionsFromType(typeID: number): Array<CmdbTypeSection> {
        return this.types.find(t => t.public_id === typeID).render_meta.sections;
    }

    /**
     * When section selection changed.
     * @param section
     */
    public onSectionChange(section: CmdbTypeSection): void {
        if (!section) {
            this.data.reference.section_name = undefined;
        } else {
            this.data.reference.section_name = section.name;
        }
        this.selectedSection = section;
        this.data.reference.selected_fields = undefined;
    }

    public onSectionFieldsChange(fields: Array<string>): void {
        this.data.reference.selected_fields = fields;
    }

    /**
     * Change the field label
     * @param change
     * @param idx
     */
    public onLabelChange(change: string, idx: string) {
        this.data[idx] = change;
        const field = this.fields.find(x => x.name === `${this.data.name}-field`);
        const fieldIdx = this.data.fields.indexOf(field);
        if (fieldIdx > -1) {
            this.data.fields[fieldIdx].label = change;
        }
    }

    /**
    * Change the field when the reference name changes.
    * 
    * This method updates the field name in both `this.data.fields` and `this.fields`.
    * It first tries to find the latest field name if the old name has been updated.
    * Then, it updates the field name accordingly and also updates `this.data.name` to the new name.
    * 
    * @param name The new name for the field.
    */
    public onNameChange(name: string) {
        let oldName = this.data.name;

        const latestField = this.fields.find(x => x.name.startsWith(oldName));
        if (latestField) {
            oldName = latestField.name.replace('-field', '');
        }

        const fieldIdx = this.data.fields.indexOf(`${oldName}-field`);
        if (fieldIdx === -1) {
            return;
        }

        const field = this.fields.find(x => x.name === `${oldName}-field`);
        if (!field) {
            return;
        }

        const newFieldName = `${name}-field`;
        this.data.fields[fieldIdx] = newFieldName;
        field.name = newFieldName;

        this.data.name = name;
    }



    /**
     * Destroy component.
     */
    public ngOnDestroy(): void {
        this.subscriber?.next();
        this.subscriber?.complete();

        if (this.activeIndexSubscription) {
            this.activeIndexSubscription.unsubscribe();
        }
    }


    /**
     * Updates the section value based on the provided new value.
     * Validates the section identifier and updates the identifier validity state.
     * @param newValue - The new value for the section.
     */
    updateSectionValue(newValue: string): void {

        this.activeIndexSubscription = this.sectionIdentifier.getActiveIndex().subscribe((index) => {
            if (index !== null && index !== undefined) {
                this.activeIndex = index;
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
     * Copies the current field identifier to clipboard
     */
    public async copyIdentifier(): Promise<void> {
        await this.copyService.copyWithFeedback(this.nameControl.value, 'section reference identifier');
    }
}
