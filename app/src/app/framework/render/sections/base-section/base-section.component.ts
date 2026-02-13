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
import { Component, Input } from '@angular/core';
import { UntypedFormGroup } from '@angular/forms';

import { CmdbTypeSection } from '../../../models/cmdb-type';
import { CmdbMode } from '../../../modes.enum';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'cmdb-base-section',
    templateUrl: './base-section.component.html',
    styleUrls: ['./base-section.component.scss'],
    standalone: false
})
export class BaseSectionComponent {
    public MODES = CmdbMode;

    // Form for every object create or edit
    @Input() public form: UntypedFormGroup;
    // Separated form for things like bulk change. Saves changes
    @Input() public changeForm: UntypedFormGroup;

    @Input() public fields: Array<any> = [];
    public values: Array<any> = [];

    @Input() public mode: CmdbMode = CmdbMode.View;
    @Input() public section: CmdbTypeSection;

/* -------------------------------------------------- GETTER/SETTER ------------------------------------------------- */
    @Input('values')
    public set Values(val: Array<any>) {
        if (val) {
            this.values = val;
        }
    }

/* ------------------------------------------------- HELPER METHODS ------------------------------------------------- */

    public getFieldByName(name: string) {
        const field: any = this.fields.find(f => f.name === name);
        switch (field?.type) {
            case 'ref': {
                field.default = parseInt(field?.default, 10);
                break;
            }
            default: {
                if (!field.default) {
                    field.default = field?.value;
                }
                break;
            }
        }
        return field;
    }


    public getValueByName(name: string) {
        const fieldFound = this.values.find(field => field.name === name);
    
        if (fieldFound === undefined) {
            return undefined;
        }

        return fieldFound.value;
    }
}
