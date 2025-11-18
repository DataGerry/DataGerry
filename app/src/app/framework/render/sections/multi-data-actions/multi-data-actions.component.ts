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
import { Component, EventEmitter, Input, OnInit, Output } from '@angular/core';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'cmdb-multi-data-actions',
    templateUrl: './multi-data-actions.component.html',
    styleUrls: ['./multi-data-actions.component.scss'],
    standalone: false
})
export class MultiDataActionsComponent implements OnInit {

    // Public id of the object
    @Input() public data: any;
    public rowIndex: number = -1; 

    @Output() public previewRowEmitter: EventEmitter<number> = new EventEmitter<number>();
    @Output() public editRowEmitter: EventEmitter<number> = new EventEmitter<number>();
    @Output() public deleteRowEmitter: EventEmitter<number> = new EventEmitter<number>();

/* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    public ngOnInit(): void {
        this.rowIndex = this.data['dg-multiDataRowIndex'];
    }

/* -------------------------------------------------- MODAL SECTION ------------------------------------------------- */

    public onPreviewRowClicked(){
        this.previewRowEmitter.emit(this.rowIndex);
    }


    public onEditRowClicked(){
        this.editRowEmitter.emit(this.rowIndex);
    }


    public onDeleteRowClicked(){
        this.deleteRowEmitter.emit(this.rowIndex);
    }
}