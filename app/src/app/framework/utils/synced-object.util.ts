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
import { RenderResult } from '../models/cmdb-render';
import { SyncLockableField } from '../models/synced-object';
/* ------------------------------------------------------------------------------------------------------------------ */

/** The person fields only the mirrored user changes. */
export const SYNCED_PERSON_FIELDS: ReadonlyArray<string> = ['display_name', 'first_name', 'last_name', 'email'];

/** The person group fields only the mapped user group changes while the group sync is on. */
export const SYNCED_PERSON_GROUP_FIELDS: ReadonlyArray<string> = ['name'];

export const PERSON_GROUP_MEMBERS_FIELD = 'members';

export const SYNCED_DELETE_REASON = 'Objects synced from user management cannot be deleted.';


/** A person mirroring a user. */
export function isSyncedPerson(result: RenderResult | null | undefined): boolean {
    return result?.object_information?.system_ref?.kind === 'user';
}


/** A person group mirroring a user group, whatever the group sync's state. */
export function isMappedPersonGroup(result: RenderResult | null | undefined): boolean {
    return result?.object_information?.system_ref?.kind === 'user_group';
}


/** A mapped person group whose name and synced members are locked by the running group sync. */
export function isLockedPersonGroup(result: RenderResult | null | undefined): boolean {
    return isMappedPersonGroup(result) && result.object_information.group_sync_active === true;
}


export function isSyncDeleteBlocked(result: RenderResult | null | undefined): boolean {
    return isSyncedPerson(result) || isLockedPersonGroup(result);
}


/** The field names a sync write lock covers on this object; empty for an unsynced one. */
export function syncLockedFieldNames(result: RenderResult | null | undefined): ReadonlyArray<string> {
    if (isSyncedPerson(result)) {
        return SYNCED_PERSON_FIELDS;
    }

    return isLockedPersonGroup(result) ? SYNCED_PERSON_GROUP_FIELDS : [];
}


/** Marks the rendered fields the sync owns, so the edit form renders them locked. */
export function applySyncLocks(result: RenderResult | null | undefined): void {
    const lockedNames = syncLockedFieldNames(result);
    const locksMembers = isLockedPersonGroup(result);
    const fields: SyncLockableField[] = result?.fields ?? [];

    for (const field of fields) {
        if (lockedNames.includes(field?.name)) {
            field.disabled = true;
        }

        if (locksMembers && field?.name === PERSON_GROUP_MEMBERS_FIELD) {
            field.lockSyncedSelections = true;
        }
    }
}
