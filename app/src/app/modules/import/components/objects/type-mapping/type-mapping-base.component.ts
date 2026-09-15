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
import { Component, EventEmitter, Input, Output } from '@angular/core';

import { DndDropEvent, DropEffect } from 'ngx-drag-drop';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'cmdb-type-mapping-base',
    template: '',
    standalone: false
})
export class TypeMappingBaseComponent {
    @Input() public parsedData: any = undefined;
    @Input() public parserConfig: any = {};

    public readonly allowedEffect: any = 'move';

    @Input() public mappingControls: any = [];
    @Input() public currentMapping: any = [];

    @Output() public mappingChange = new EventEmitter();


    public onDragged(item: any, list: any[], effect: DropEffect) {
        if (effect === 'move') {
            const index = list.indexOf(item);
            list.splice(index, 1);
        }
    }


    public moveControl(item: any, from: any[], targetIdx: number, to: any[]) {
        from.splice(from.indexOf(item), 1);
        item.value = targetIdx;
        to.splice(targetIdx, 1, item);
    }


    public onRemove(index: number, list: any[], original?: any[]) {
        if (original && (list[index] !== undefined)) {
            const originalData = list[index];
            original.splice(original.length, 0, originalData);
        }

        list.splice(index, 1, '');
        this.mappingChange.emit(this.currentMapping);
    }


    public onDrop(event: DndDropEvent, list: any[], index?: number, original?: any[]) {
        if (typeof index === undefined) {
            index = list.length;
        } else {
            if (original && (list[index] !== undefined)) {
                const originalData = list[index];
                original.splice(original.length, 0, originalData);
            }
        }

        event.data.value = index;
        list.splice(index, 1, event.data);
        this.mappingChange.emit(this.currentMapping);
    }
}
