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
import { Component, OnInit, Input, ViewChild, EventEmitter, Output } from '@angular/core';
import { UntypedFormControl, UntypedFormGroup, Validators } from '@angular/forms';

import { DocapiBuilderTypeStepBaseComponent } from '../docapi-builder-type-step-base/docapi-builder-type-step-base.component';
import { CmdbMode } from '../../../../framework/modes.enum';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'cmdb-docapi-settings-builder-type-step',
    templateUrl: './docapi-builder-type-step.component.html',
    styleUrls: ['./docapi-builder-type-step.component.scss'],
    standalone: false
})
export class DocapiBuilderTypeStepComponent implements OnInit {

    @Input()
    set preData(data: any) {
        if (data !== undefined) {
            this.typeForm?.patchValue(data);

            if (data.template_parameters) {
                this.typeParamPreData = data?.template_parameters;
            }

            this.buildTemplateTypeOptions();
            this.checkTypeChildValid();

        }
    }

    @Input() public mode: CmdbMode;
    public modes = CmdbMode;
    public typeForm: UntypedFormGroup;
    public docTypeSelect: any[] = [];

    @Output() public typeParamReady = new EventEmitter<DocapiBuilderTypeStepBaseComponent>();

    private _typeParamComponent: DocapiBuilderTypeStepBaseComponent;

    @ViewChild('typeparam')
    set typeParamComponent(component: DocapiBuilderTypeStepBaseComponent) {
        this._typeParamComponent = component;
        this.checkTypeChildValid();
        if (component) {
            this.typeParamReady.emit(component);
        }
    }

    get typeParamComponent(): DocapiBuilderTypeStepBaseComponent {
        return this._typeParamComponent;
    }
    public typeParamPreData: any;

    public typeValid: boolean = false;
    public typeChildValid: boolean = false;

    public get isStepValid(): boolean {
        if (!this.typeForm?.valid) {
            return false;
        }

        return !!this.typeParamComponent?.typeParamForm?.valid;
    }

    @Output() public formValidEmitter: EventEmitter<boolean>;

    /**
    * Updates the validity of the child components based on the type parameter
    */
    private checkTypeChildValid() {
        this.typeValid = this.typeForm?.valid;
        this.typeChildValid = !!this.typeParamComponent?.typeParamForm?.valid;
        this.formValidEmitter?.emit(this.isStepValid);
    }


    /* ------------------------------------------------------------------------------------------------------------------ */
    /*                                                     LIFE CYCLE                                                     */
    /* ------------------------------------------------------------------------------------------------------------------ */

    constructor() {
        // setup form
        this.formValidEmitter = new EventEmitter<boolean>();
        this.typeForm = new UntypedFormGroup({
            template_type: new UntypedFormControl('', Validators.required)
        });
    }


    public ngOnInit(): void {
        this.buildTemplateTypeOptions();
        this.checkTypeChildValid();
        this.typeForm?.valueChanges?.subscribe(() => {
            this.checkTypeChildValid();
        });
    }

    public onTypeParamValidationChange(isValid: boolean): void {
        this.typeChildValid = isValid;
        this.formValidEmitter?.emit(this.isStepValid);
    }

    private buildTemplateTypeOptions(): void {
        const isEditMode = this.mode === CmdbMode.Edit;
        const currentType = this.typeForm?.get('template_type')?.value;
        const allowObject = isEditMode && currentType === 'OBJECT';

        const objectOption = {
            label: 'Object Template (Deprecated)',
            content: 'OBJECT',
            description: 'Template for single objects',
            disabled: !allowObject
        };
        const defaultOption = {
            label: 'Default Template',
            content: 'DEFAULT',
            description: ''
        };

        if (isEditMode) {
            this.docTypeSelect = allowObject ? [objectOption, defaultOption] : [defaultOption];
        } else {
            this.docTypeSelect = [defaultOption];
        }
    }
}
