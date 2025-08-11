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

* You should have received a copy of the GNU Affero General Public License
* along with this program. If not, see <https://www.gnu.org/licenses/>.
*/
import {
    Component,
    ComponentFactoryResolver, HostBinding,
    Input,
    OnInit,
    ViewChild,
    ViewContainerRef
} from '@angular/core';
import { Column } from '../../table.types';
import { Router } from '@angular/router';

@Component({
    selector: 'td[table-cell]',
    templateUrl: './table-cell.component.html',
    styleUrls: ['./table-cell.component.scss'],
    standalone: false
})
export class TableCellComponent<T> {

    constructor(private router: Router) { }

    // noinspection JSMismatchedCollectionQueryUpdate
    @HostBinding('class') private cssClasses: Array<string>;
    @HostBinding('class') private cellClasses: Array<string>;

    /**
     * When column is hidden, add css class hidden to cell.
     */
    @HostBinding('class.hidden') @Input() public hidden: boolean = false;

    /**
   * getting boolean value to ensure if want Edit and View Route 
   */
    @Input() isViewAndEditRequired: Boolean;

    /**
     * Row index which this cell is in.
     */
    @Input() rowIndex: number;

    public data: any;

    public column: Column;

    publicID: string;
    isSingleClick: Boolean = true;

    @Input('column')
    public set Column(col: Column) {
        this.column = col;
        this.hidden = this.column.hidden;
        this.cssClasses = this.column.cssClasses || [];
        this.cellClasses = this.column.cellClasses || [];
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

        // Extracting PublicID from item
        if (item && item['object_information'] && item['object_information']['object_id']) {
            this.publicID = item['object_information']['object_id'];
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


    /**
     * Function to handle a single click for viewing an object
     */
    handleObjectView() {
        if (this.isViewAndEditRequired && this.column.name !== 'actions') {
            this.isSingleClick = true;

            setTimeout(() => {
                if (this.isSingleClick) {
                    this.generateRouterLink('view', this.publicID);
                }
            }, 300);
        }
    }


    /**
     * Function to handle a double click for editing an object
     */
    handleObjectEdit() {
        if (this.isViewAndEditRequired && this.column.name !== 'actions') {
            this.isSingleClick = false;
            this.generateRouterLink('edit', this.publicID);
        }
    }


    /**
     * Function to generate a router link based on the action and publicID
     * @param action - The action to perform, e.g., 'view', 'edit', etc.
     * @param publicID - The unique identifier associated with the object
     */
    generateRouterLink(action: string, publicID: string) {
        this.router.navigate(['/', 'framework', 'object', action, publicID]);
    }

}
