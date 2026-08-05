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
import { TemplateRef } from '@angular/core';

import { UserSettingPayload } from '../../management/user-settings/models/user-setting';
/* ------------------------------------------------------------------------------------------------------------------ */

/**
 * Table row grouping interface
 */
export interface GroupRowsBy<T = any> {
    group: (items: Array<T>, callback) => Array<RowGroup>;
    src: (item: T, groups: Array<RowGroup>) => RowGroup;
}


/**
 * Single group section of a table row group result
 */
export class RowGroup<I = any> {
    public items: Array<I> = [];
    public header: any = '';

    constructor(items: Array<I>, header?: any) {
      this.items = items;
      this.header = header;
    }


    public get count(): number {
      return this.items.length;
    }
}


/**
 * Order of sorting
 */
export enum SortDirection {
    NONE = 0,
    ASCENDING = 1,
    DESCENDING = -1
}


/**
 * Interface for Sort/Order combination
 */
export interface Sort {
    name: string;
    order: SortDirection;
}


/**
 * Interface for a table header.
 */
export interface Column {
    // Displayed name
    display?: any;

    // Data value
    data: any;

    // Identifier
    name: string;

    // Field type (text, checkbox, reference etc.)
    type?: string;

    // Field is hidden
    hidden?: boolean;

    // Field cant be toggled
    fixed?: boolean;

    // Sortable
    sortable?: boolean;

    // Searchable
    searchable?: boolean;

    // Got row template
    template?: TemplateRef<any>;

    /**
     * List of extra css classes for
     * head and cells in this column
     */
    cssClasses?: Array<string>;

    /**
     * List of extra css classes for
     * cells in this column
     */
    cellClasses?: Array<string>;

    /**
     * List of direct styles for
     * head and cells in this column
     */
    style?: { [klass: string]: any };

    /**
     * Data parser
     * @param data
     * @param item
     * @param column
     * @param index
     */
    render?(data: any, item?: any, column?: Column, index?: number);
}


/**
 * A table state.
 */
export interface TableState {
    name?: string;
    visibleColumns?: Array<string>;
    page?: number;
    pageSize?: number;
    sort?: Sort;
}


/**
 * Table state payload for saving table state data into the user settings
 */
export class TableStatePayload implements UserSettingPayload {
    public id: string;
    public tableStates: Array<TableState>;
    public currentState?: TableState;


    public constructor(id: string, states: Array<TableState>, currentState?: TableState) {
        this.id = id;
        this.tableStates = states;
        this.currentState = currentState;
    }
}
