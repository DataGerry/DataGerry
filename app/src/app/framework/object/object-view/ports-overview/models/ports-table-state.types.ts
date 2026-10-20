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
/* ------------------------------------------------------------------------------------------------------------------ */

/** The user setting a ports table keeps its saved column views in, shared by every object. */
export interface PortsTableStateKey {
    /** Becomes the setting's resource: `/framework/object-ports-standard` → `framework-object-ports-standard`. */
    stateUrl: string;
    payloadId: string;
}

export const STANDARD_PORTS_TABLE_STATE: PortsTableStateKey = {
    stateUrl: '/framework/object-ports-standard',
    payloadId: 'object-ports-table'
};

export const PATCH_PANEL_TABLE_STATE: PortsTableStateKey = {
    stateUrl: '/framework/object-ports-patch-panel',
    payloadId: 'object-patch-panel-table'
};
