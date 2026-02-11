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
import { Component, Input, Output, EventEmitter } from '@angular/core';
import { UntypedFormGroup } from '@angular/forms';

import { CmdbMode } from '../../../../framework/modes.enum';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'cmdb-docapi-builder-type-step-base',
    templateUrl: './docapi-builder-type-step-base.component.html',
    styleUrls: ['./docapi-builder-type-step-base.component.scss'],
    standalone: false
})
export class DocapiBuilderTypeStepBaseComponent {

    @Input()
    set preData(data: any) {
        if (data) {
            this.typeParamForm?.patchValue(data);
        }
    }

    @Input() public mode: CmdbMode;

    @Output() public formValidationEmitter: EventEmitter<boolean>;
    public formValid: boolean = false;
    public typeParamForm: UntypedFormGroup;
    public modes = CmdbMode;


    constructor() {
        this.formValidationEmitter = new EventEmitter<boolean>();
    }
}
