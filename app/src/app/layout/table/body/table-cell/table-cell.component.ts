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

* You should have received a copy of the GNU Affero General Public License
* along with this program. If not, see <https://www.gnu.org/licenses/>.
*/
import {
    Component,
    HostBinding,
    Input,
} from '@angular/core';
import { Column } from '../../table.types';
import { getColumnClasses } from '../../table-column-layout';

@Component({
    selector: 'td[table-cell]',
    templateUrl: './table-cell.component.html',
    styleUrls: ['./table-cell.component.scss'],
    standalone: false
})
export class TableCellComponent<T> {

    // noinspection JSMismatchedCollectionQueryUpdate
    @HostBinding('class') protected cssClasses: Array<string>;

    /**
     * When column is hidden, add css class hidden to cell.
     */
    @HostBinding('class.hidden') @Input() public hidden: boolean = false;

    /**
     * Row index which this cell is in.
     */
    @Input() rowIndex: number;

    public data: any;

    public column: Column;

    @Input('column')
    public set Column(col: Column) {
        this.column = col;
        this.hidden = this.column.hidden;
        this.cssClasses = getColumnClasses(this.column, this.column.cssClasses, this.column.cellClasses);
    }

    public item: T;

    @Input('item')
    public set Item(item: T) {
        this.item = item;
        if (this.column.data) {
            const cellData = TableCellComponent.resolve(this.column.data, this.item);
            if (this.column.render) {
                this.data = this.column.render(cellData, this.item, this.column, this.rowIndex);
            } else {
                this.data = cellData;
            }

        }
    }


    /**
     * Resolves a given objects path to a value.
     * @param path to the property
     * @param obj resolvable object
     * @param separator ident
     */
    static resolve(path, obj, separator = '.') {
        const properties = Array.isArray(path) ? path : path.split(separator);
        return properties.reduce((prev, curr) => prev && prev[curr], obj);
    }

}
