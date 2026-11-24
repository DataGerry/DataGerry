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
import { TestBed } from '@angular/core/testing';
import { of, throwError } from 'rxjs';

import { LoaderService } from 'src/app/core/services/loader.service';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { PermissionService } from 'src/app/modules/auth/services/permission.service';
import { PersonSyncService } from '../../services/person-sync.service';
import { GroupSyncStore } from './group-sync.store';
/* ------------------------------------------------------------------------------------------------------------------ */

describe('GroupSyncStore', () => {

    let personSync: jasmine.SpyObj<PersonSyncService>;
    let toast: jasmine.SpyObj<ToastService>;
    let loader: jasmine.SpyObj<LoaderService>;

    function createStore(hasRight: boolean): GroupSyncStore {
        const permissions = jasmine.createSpyObj<PermissionService>('PermissionService', ['hasRight', 'hasExtendedRight']);
        permissions.hasRight.and.returnValue(hasRight);
        permissions.hasExtendedRight.and.returnValue(false);

        TestBed.configureTestingModule({
            providers: [
                GroupSyncStore,
                { provide: PersonSyncService, useValue: personSync },
                { provide: PermissionService, useValue: permissions },
                { provide: LoaderService, useValue: loader },
                { provide: ToastService, useValue: toast }
            ]
        });

        return TestBed.inject(GroupSyncStore);
    }

    beforeEach(() => {
        personSync = jasmine.createSpyObj<PersonSyncService>(
            'PersonSyncService', ['getGroupSync', 'mapUserGroup', 'unmapUserGroup']);
        toast = jasmine.createSpyObj<ToastService>('ToastService', ['success', 'error']);
        loader = jasmine.createSpyObj<LoaderService>('LoaderService', ['show', 'hide']);

        personSync.getGroupSync.and.returnValue(of({
            active: true,
            mappings: [{ user_group_id: 9811, person_group_id: 3 }]
        }));
    });


    it('reads nothing without the sync right', () => {
        const store = createStore(false);

        store.load();

        expect(personSync.getGroupSync).not.toHaveBeenCalled();
        expect(store.groupSync()).toBeNull();
    });


    it('loads the mappings behind the loader', () => {
        const store = createStore(true);

        store.load();

        expect(store.mappingsByUserGroup().get(9811)?.person_group_id).toBe(3);
        expect(loader.show).toHaveBeenCalledTimes(1);
        expect(loader.hide).toHaveBeenCalledTimes(1);
        expect(store.isBusy()).toBeFalse();
    });


    it('adds a mapping and keeps the persons who left', () => {
        const left = [{ person_group_id: 9821, person_ids: [1] }];
        personSync.mapUserGroup.and.returnValue(of({ left, result: { user_group_id: 9812, person_group_id: 9821 } }));
        const store = createStore(true);
        store.load();

        store.map(9812, { person_group_id: 9821 }, 'None');

        expect(personSync.mapUserGroup).toHaveBeenCalledWith(9812, { person_group_id: 9821 });
        expect(store.mappingsByUserGroup().get(9812)?.person_group_id).toBe(9821);
        expect(store.lastPass()).toEqual({ left });
        expect(toast.success).toHaveBeenCalledWith('User group None was mapped!');
    });


    it('removes an unmapped user group', () => {
        personSync.unmapUserGroup.and.returnValue(of({ user_group_id: 9811, person_group_id: 3 }));
        const store = createStore(true);
        store.load();

        store.unmap(9811, 'Field Service');

        expect(store.mappingsByUserGroup().has(9811)).toBeFalse();
    });


    it('shows a refusal and keeps the mappings as they were', () => {
        personSync.mapUserGroup.and.returnValue(throwError(() => ({
            status: 400,
            error: { message: 'User group 9811 is mapped to person group 3 already - unmap it first!' }
        })));
        const store = createStore(true);
        store.load();

        store.map(9811, { type_id: 9803 }, 'Field Service');

        expect(toast.error).toHaveBeenCalledWith('User group 9811 is mapped to person group 3 already - unmap it first!');
        expect(store.mappingsByUserGroup().get(9811)?.person_group_id).toBe(3);
        expect(store.isBusy()).toBeFalse();
    });
});
