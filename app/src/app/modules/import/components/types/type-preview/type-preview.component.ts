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
* along with this program.  If not, see <https://www.gnu.org/licenses/>.
*/
import { Component, Input } from '@angular/core';
import { UntypedFormGroup} from '@angular/forms';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'cmdb-type-preview',
    templateUrl: './type-preview.component.html',
    styleUrls: ['./type-preview.component.scss'],
    standalone: false
})
export class TypePreviewComponent {
    private fileForm: UntypedFormGroup;
    public filterTypes: string = '';


    @Input('data')
    public set data(value: UntypedFormGroup) {
        this.fileForm = value;
    }


    public get data() {
        return this.fileForm;
    }


    public removeFromFile(index: number) {
        this.data.get('file').value.splice(index, 1);
    }


    handleChange(evt) {
        this.data.get('action').setValue(evt.target.value);
    }
}
