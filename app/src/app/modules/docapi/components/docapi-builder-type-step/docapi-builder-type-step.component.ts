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

            this.checkTypeChildValid();

        }
    }

    @Input() public mode: CmdbMode;
    public modes = CmdbMode;
    public typeForm: UntypedFormGroup;
    public readonly docTypeSelect: any[] = [
        { label: 'Object Template', content: 'OBJECT', description: 'Template for single objects' },
        { label: 'Default Template', content: 'DEFAULT', description: '' }
    ];

    @ViewChild('typeparam')
    public typeParamComponent: DocapiBuilderTypeStepBaseComponent;
    public typeParamPreData: any;

    public typeValid: boolean = false;
    public typeChildValid: boolean = false;

    @Output() public formValidEmitter: EventEmitter<boolean>;

    /**
    * Updates the validity of the child components based on the type parameter
    */
    private checkTypeChildValid() {
        this.typeChildValid = this.typeParamComponent ? this.typeParamComponent?.formValid : true;
        this.formValidEmitter?.emit(this.typeValid && this.typeChildValid);
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
        this.typeForm?.valueChanges?.subscribe(() => {
            this.typeValid = this.typeForm?.valid;
            this.formValidEmitter?.emit(this.typeValid && this.typeChildValid);
        });
    }
}
