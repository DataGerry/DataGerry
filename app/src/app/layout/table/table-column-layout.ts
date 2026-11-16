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

import { Column } from './table.types';

/** The table owns column alignment, so per-column alignment classes and styles are dropped. */
const ALIGNMENT_CLASSES = new Set(['text-center', 'text-start', 'text-end', 'text-left', 'text-right']);
const ALIGNMENT_STYLES = new Set(['text-align', 'textAlign']);

const ACTIONS_COLUMN_CLASS = 'table-col-actions';

const styleCache = new WeakMap<object, { [key: string]: unknown }>();


export function isActionsColumn(column: Column): boolean {
    return typeof column?.display === 'string' && column.display.trim().toLowerCase() === 'actions';
}


export function getColumnClasses(column: Column, ...classLists: Array<Array<string> | undefined>): Array<string> {
    const classes = classLists
        .flatMap(list => list ?? [])
        .filter(cssClass => !ALIGNMENT_CLASSES.has(cssClass));

    if (isActionsColumn(column)) {
        classes.push(ACTIONS_COLUMN_CLASS);
    }

    return [...new Set(classes)];
}


export function getColumnStyle(column: Column): { [key: string]: unknown } | null {
    const style = column?.style;

    if (!style) {
        return null;
    }

    let cleaned = styleCache.get(style);

    if (!cleaned) {
        cleaned = Object.fromEntries(Object.entries(style).filter(([key]) => !ALIGNMENT_STYLES.has(key)));
        styleCache.set(style, cleaned);
    }

    return cleaned;
}
