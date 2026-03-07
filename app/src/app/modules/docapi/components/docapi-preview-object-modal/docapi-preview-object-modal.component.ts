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
import { Component, Input, OnInit } from '@angular/core';
import { NgbActiveModal } from '@ng-bootstrap/ng-bootstrap';
import { RenderResult } from 'src/app/framework/models/cmdb-render';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'cmdb-docapi-preview-object-modal',
    templateUrl: './docapi-preview-object-modal.component.html',
    styleUrls: ['./docapi-preview-object-modal.component.scss'],
    standalone: false
})
export class DocapiPreviewObjectModalComponent implements OnInit {

    @Input() templateType: string = 'OBJECT';
    @Input() templateTypeId: number | null = null;

    public typeIds: number[] = [];
    public allObjects = false;
    public selectedObject: RenderResult | null = null;

/* ------------------------------------------------------------------------------------------------------------------ */
/*                                                     LIFE CYCLE                                                     */
/* ------------------------------------------------------------------------------------------------------------------ */

    constructor(public activeModal: NgbActiveModal) {

    }

    public ngOnInit(): void {
        if (this.templateType === 'OBJECT' && this.templateTypeId) {
            this.typeIds = [this.templateTypeId];
            this.allObjects = false;
            return;
        }

        this.allObjects = true;
    }

/* ------------------------------------------------ HELPER FUNCTIONS ------------------------------------------------ */

    public onObjectSelectionChange(selectedObject: RenderResult | RenderResult[] | null): void {
        if (!selectedObject) {
            this.selectedObject = null;
            return;
        }

        this.selectedObject = Array.isArray(selectedObject)
            ? selectedObject[0] || null
            : selectedObject;
    }


    public preview(): void {
        const selectedObjectId = this.selectedObject?.object_information?.object_id;
        if (!selectedObjectId) {
            return;
        }

        this.activeModal.close(selectedObjectId);
    }


    public cancel(): void {
        this.activeModal.dismiss();
    }

}
