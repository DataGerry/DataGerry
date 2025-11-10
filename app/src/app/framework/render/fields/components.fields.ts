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
import { AbstractControl, UntypedFormGroup } from '@angular/forms';

import { ToastService } from '../../../layout/toast/toast.service';

import { CmdbMode } from '../../modes.enum';
import { CmdbMultiDataSection, CmdbTypeSection } from '../../models/cmdb-type';
/* ------------------------------------------------------------------------------------------------------------------ */
@Component({
    template: '',
    standalone: false
})
export class RenderFieldComponent {
    // Section of this field
    protected section: CmdbTypeSection | CmdbMultiDataSection;

    @Input('section')
    public set Section(value: CmdbTypeSection | CmdbMultiDataSection) {
            this.section = value;
    }

    protected innerData: any;
    public innerValue: any;
    public MODES = CmdbMode;
    public toast: ToastService;

    @Input() public mode: CmdbMode = this.MODES.View;
    @Input() public parentFormGroup: UntypedFormGroup;
    @Input() public changeForm: UntypedFormGroup;

/* ------------------------------------------------- GETTER / SETTER ------------------------------------------------ */

    @Input('data')
    public set data(value: any) {
        this.innerData = value;
    }

    public get data(): any {
        return this.innerData;
    }

    @Input('value')
    public set value(value: any) {
        this.innerValue = value;
    }

    public get value(): any {
        if (this.data.value && (!this.innerValue || this.innerValue === '')) {
            this.innerValue = this.data.value;
        }

        return this.innerValue;
    }

    public get controller(): AbstractControl {
        return this.parentFormGroup.get(this.data.name);
    }

/* ------------------------------------------------- HELPER METHODS ------------------------------------------------- */

    public copyToClipboard() {
        const selBox = document.createElement('textarea');
        selBox.value = this.controller.value;
        this.generateDataForClipboard(selBox);
    }


    protected generateDataForClipboard(selBox: any) {
        selBox.style.position = 'fixed';
        selBox.style.left = '0';
        selBox.style.top = '0';
        selBox.style.opacity = '0';
        document.body.appendChild(selBox);
        selBox.focus();
        selBox.select();
        this.showToast(selBox);
    }


    protected showToast(selBox: any) {
        document.execCommand('copy');
        document.body.removeChild(selBox);
        this.toast.info('Content was copied to clipboard');
    }
}
