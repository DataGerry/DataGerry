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

/** The flags a rendered field carries when the sync owns all or part of it on the edit screen. */
export interface SyncLockableField {
    name?: string;
    /** The whole field is read-only; render-element disables its control. */
    disabled?: boolean;
    /** A person selector whose synced persons can be neither added nor removed. */
    lockSyncedSelections?: boolean;
}
