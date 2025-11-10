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
import { Component, Input } from '@angular/core';
import { UntypedFormControl, UntypedFormGroup } from '@angular/forms';

import { CmdbMode } from '../../../../framework/modes.enum';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'cmdb-docapi-builder-style-step',
    templateUrl: './docapi-builder-style-step.component.html',
    styleUrls: ['./docapi-builder-style-step.component.scss'],
    standalone: false
})
export class DocapiBuilderStyleStepComponent {
    @Input()
    set preData(data: any) {
        if (data !== undefined) {
        this.styleForm?.patchValue(data);
        }
    }

    @Input() public mode: CmdbMode;
    public modes = CmdbMode;
    public styleForm: UntypedFormGroup;


    constructor() {
        this.styleForm = new UntypedFormGroup({
            template_style: new UntypedFormControl('')
        });
    }
}
