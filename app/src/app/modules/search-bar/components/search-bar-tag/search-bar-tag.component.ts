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
import { Component, ElementRef, EventEmitter, Input, Output, ViewChild } from '@angular/core';

import { SearchBarTag } from './search-bar-tag';

@Component({
    selector: 'cmdb-search-bar-tags',
    templateUrl: './search-bar-tag.component.html',
    styleUrls: ['./search-bar-tag.component.scss'],
    standalone: false
})
export class SearchBarTagComponent {

    // Elements
    @ViewChild('dropdownTrigger') dropdownTrigger: ElementRef;

    // Events
    @Input() public tag: SearchBarTag;
    @Output() public changeEmitter: EventEmitter<SearchBarTag>;
    @Output() public deleteEmitter: EventEmitter<SearchBarTag>;


    public constructor() {
        /**
         * Default constructor
         * Change form is deactivated
         */
        this.changeEmitter = new EventEmitter<SearchBarTag>();
        this.deleteEmitter = new EventEmitter<SearchBarTag>();
    }


    public emitDelete() {
        this.deleteEmitter.emit(this.tag);
    }
}
