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
import { BehaviorSubject } from 'rxjs';
/* ------------------------------------------------------------------------------------------------------------------ */


export const ROOT_LOCATION = {
    public_id: 1,
    name: 'Root',
    icon: 'fas fa-globe'
} as const;

/**
 * View-model of a single location node inside the tree-select panel: the raw lazy node plus the
 * selection/exclusion state and the lazy-loading bookkeeping the tree needs.
 */
export interface LocationTreeSelectNode {
    public_id: number;
    name: string;
    icon: string;
    parent: number;
    object_id: number;
    has_children: boolean;
    /** false when the location's type may not be chosen as a parent */
    selectable: boolean;
    /** true when the node is the edited object itself or one of its descendants */
    excluded: boolean;
    children$: BehaviorSubject<LocationTreeSelectNode[]>;
    loaded: boolean;
    loading: boolean;
}

/**
 * Emitted whenever the selection changes; `null` means the value was cleared.
 */
export interface LocationSelection {
    public_id: number;
    object_id: number;
    name: string;
    icon: string;
}
