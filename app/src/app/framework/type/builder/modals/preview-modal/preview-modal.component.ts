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
* along with this program.  If not, see <https://www.gnu.org/licenses/>.
*/
import { Component, Input } from '@angular/core';
import { UntypedFormGroup } from '@angular/forms';

import { NgbActiveModal } from '@ng-bootstrap/ng-bootstrap';

import { CmdbMode } from '../../../../modes.enum';
/* ------------------------------------------------------------------------------------------------------------------ */
@Component({
    selector: 'cmdb-preview-modal',
    templateUrl: './preview-modal.component.html',
    styleUrls: ['./preview-modal.component.scss'],
    standalone: false
})
export class PreviewModalComponent {
    @Input() sections: any[];
    @Input() saveValues: boolean = false;
    @Input() editValues: boolean = false;
    @Input() activateViewMode: boolean = false;

    public renderForm: UntypedFormGroup;
    public modes = CmdbMode;

/* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    constructor(public activeModal: NgbActiveModal) {
        this.renderForm = new UntypedFormGroup({});
    }


    getViewMode() {
        return this.activateViewMode ? CmdbMode.View : CmdbMode.Create
    }
}
