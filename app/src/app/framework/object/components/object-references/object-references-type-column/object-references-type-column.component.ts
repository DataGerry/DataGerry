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

import { CmdbObject } from '../../../../models/cmdb-object';
import { RenderResult } from '../../../../models/cmdb-render';
/* ------------------------------------------------------------------------------------------------------------------ */
@Component({
    selector: 'cmdb-object-references-type-column',
    templateUrl: './object-references-type-column.component.html',
    styleUrls: ['./object-references-type-column.component.scss'],
    standalone: false
})
export class ObjectReferencesTypeColumnComponent {
    public isSectionRef: boolean = false;
    public isFieldRef: boolean = false;
    public isMdsRef: boolean = false;

    // ID of the referenced object
    @Input() public objectID: number;

    // Reference object
    public renderResult: CmdbObject | RenderResult;


    @Input('object')
    public set Object(obj: CmdbObject | RenderResult) {
        if (obj) {
            this.renderResult = obj;
            this.isSectionRef = this.refTypeIsInFields(obj.fields, 'ref-section-field');
            this.isFieldRef = this.refTypeIsInFields(obj.fields, 'ref');
            this.isMdsRef = this.refTypeIsInMDS();
        }

    }

/* ------------------------------------------------- HELPER METHODS ------------------------------------------------- */

    private refTypeIsInMDS(): boolean {
        if (this.renderResult.multi_data_sections) {
            for (let mdsEntry of this.renderResult.multi_data_sections) {
                for (let mdsValue of mdsEntry.values) {
                    for( let dataSet of mdsValue.data) {
                        if(dataSet.value == this.objectID && this.isRefField(dataSet.name)) {
                            return true;
                        }
                    }
                }
            }
        }

        return false;
    }


    private isRefField(fieldName: string): boolean {
        for (let aField of this.renderResult.fields) {
            if (aField.name == fieldName && aField.type == "ref") {
                return true;
            }
        }

        return false;
    }


    /**
     * Check if a ref type is in fields
     */
    private refTypeIsInFields(fields: Array<any>, type: string): boolean {
        return fields.find(f => f.type === type && f.value === this.objectID) !== undefined;
    }
}
