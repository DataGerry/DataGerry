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
import { UntypedFormControl, UntypedFormGroup, Validators } from '@angular/forms';

import { TypeService } from '../../../../framework/services/type.service';

import { DocapiBuilderTypeStepBaseComponent } from '../docapi-builder-type-step-base/docapi-builder-type-step-base.component';
import { CmdbType } from '../../../../framework/models/cmdb-type';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'cmdb-docapi-builder-type-step-object',
    templateUrl: './docapi-builder-type-step-object.component.html',
    styleUrls: ['./docapi-builder-type-step-object.component.scss'],
    standalone: false
})
export class DocapiBuilderTypeStepObjectComponent extends DocapiBuilderTypeStepBaseComponent implements OnInit {
    public objectTypeList: Array<CmdbType> = [];

    constructor(private typeService: TypeService) {
        super();

        this.typeParamForm = new UntypedFormGroup({
            type: new UntypedFormControl('', Validators.required)
        });
    }


    public ngOnInit(): void {
        this.typeParamForm?.valueChanges?.subscribe(() => {
            this.formValid = this.typeParamForm?.valid;
            this.formValidationEmitter?.emit(this.formValid);
        });

        this.formValid = this.typeParamForm?.valid;
        this.formValidationEmitter?.emit(this.formValid);

        this.typeService?.getTypeList()?.subscribe((value: CmdbType[]) => this.objectTypeList = value);
    }
}
