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
import { SystemRef } from 'src/app/management/models/person-sync';
import {
    SYNCED_PERSON_FIELDS,
    applySyncLocks,
    isLockedPersonGroup,
    isMappedPersonGroup,
    isSyncDeleteBlocked,
    isSyncedPerson,
    syncLockedFieldNames
} from './synced-object.util';
/* ------------------------------------------------------------------------------------------------------------------ */

function result(systemRef?: SystemRef, groupSyncActive?: boolean, fieldNames: string[] = []): RenderResult {
    return {
        object_information: { object_id: 1, system_ref: systemRef, group_sync_active: groupSyncActive },
        fields: fieldNames.map(name => ({ name }))
    } as unknown as RenderResult;
}


describe('synced-object.util', () => {

    describe('classification', () => {
        it('treats an object without a system_ref as unsynced', () => {
            const plain = result();

            expect(isSyncedPerson(plain)).toBeFalse();
            expect(isMappedPersonGroup(plain)).toBeFalse();
            expect(isSyncDeleteBlocked(plain)).toBeFalse();
            expect(syncLockedFieldNames(plain)).toEqual([]);
        });

        it('tolerates a missing render result', () => {
            expect(isSyncedPerson(undefined)).toBeFalse();
            expect(isSyncDeleteBlocked(null)).toBeFalse();
        });

        it('blocks deleting a synced person and locks its synced fields', () => {
            const person = result({ kind: 'user', id: 11 });

            expect(isSyncedPerson(person)).toBeTrue();
            expect(isSyncDeleteBlocked(person)).toBeTrue();
            expect(syncLockedFieldNames(person)).toEqual(SYNCED_PERSON_FIELDS);
        });

        it('locks a mapped person group only while the group sync is on', () => {
            const on = result({ kind: 'user_group', id: 10 }, true);
            const off = result({ kind: 'user_group', id: 10 }, false);

            expect(isLockedPersonGroup(on)).toBeTrue();
            expect(isSyncDeleteBlocked(on)).toBeTrue();
            expect(syncLockedFieldNames(on)).toEqual(['name']);

            expect(isMappedPersonGroup(off)).toBeTrue();
            expect(isLockedPersonGroup(off)).toBeFalse();
            expect(isSyncDeleteBlocked(off)).toBeFalse();
            expect(syncLockedFieldNames(off)).toEqual([]);
        });
    });


    describe('applySyncLocks', () => {
        it('disables the synced person fields and leaves the person\'s own fields free', () => {
            const person = result({ kind: 'user', id: 11 }, undefined, ['display_name', 'email', 'phone_number']);

            applySyncLocks(person);

            const fields = person.fields as SyncLockableField[];
            expect(fields.find(field => field.name === 'display_name').disabled).toBeTrue();
            expect(fields.find(field => field.name === 'email').disabled).toBeTrue();
            expect(fields.find(field => field.name === 'phone_number').disabled).toBeUndefined();
        });

        it('locks the name and the synced members of a locked person group', () => {
            const group = result({ kind: 'user_group', id: 10 }, true, ['name', 'email', 'members']);

            applySyncLocks(group);

            const fields = group.fields as SyncLockableField[];
            expect(fields.find(field => field.name === 'name').disabled).toBeTrue();
            expect(fields.find(field => field.name === 'email').disabled).toBeUndefined();
            expect(fields.find(field => field.name === 'members').lockSyncedSelections).toBeTrue();
            expect(fields.find(field => field.name === 'members').disabled).toBeUndefined();
        });

        it('changes nothing on a mapped group while the group sync is off', () => {
            const group = result({ kind: 'user_group', id: 10 }, false, ['name', 'members']);

            applySyncLocks(group);

            expect((group.fields as SyncLockableField[]).every(field => !field.disabled && !field.lockSyncedSelections))
                .toBeTrue();
        });
    });
});
