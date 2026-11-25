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
import { HttpResponse } from '@angular/common/http';
import { of } from 'rxjs';

import { ApiCallService } from '../../services/api-call.service';
import { UserSyncRequest } from '../models/person-sync';
import { PersonSyncService } from './person-sync.service';
/* ------------------------------------------------------------------------------------------------------------------ */

function answer<T>(body: T) {
    return of(new HttpResponse({ body, status: 200 }));
}


describe('PersonSyncService', () => {

    let service: PersonSyncService;
    let api: jasmine.SpyObj<ApiCallService>;

    const settings: UserSyncRequest = { active: true, default_type_id: 9801, type_overrides: [] };

    beforeEach(() => {
        api = jasmine.createSpyObj<ApiCallService>('ApiCallService', ['callGet', 'callPut', 'callPost', 'callDelete']);

        TestBed.configureTestingModule({ providers: [{ provide: ApiCallService, useValue: api }] });
        service = TestBed.inject(PersonSyncService);
    });


    it('reads the user sync settings from the result', (done) => {
        api.callGet.and.returnValue(answer({ result: settings }));

        service.getUserSync().subscribe((value) => {
            expect(api.callGet.calls.mostRecent().args[0]).toBe('person_sync/users');
            expect(value).toEqual(settings);
            done();
        });
    });


    it('stores the whole settings object and answers the pass with its counts', (done) => {
        const pass = { created: 2, edited: 0, moved: 0, copied: 0, left: [], result: settings };
        api.callPut.and.returnValue(answer(pass));

        service.updateUserSync({ ...settings, on_blocked: 'copy' }).subscribe((value) => {
            expect(api.callPut.calls.mostRecent().args.slice(0, 2))
                .toEqual(['person_sync/users', { ...settings, on_blocked: 'copy' }]);
            expect(value).toEqual(pass);
            done();
        });
    });


    it('posts the dry run and reads its relocations', (done) => {
        const check = { relocations: [], blocked: 0 };
        api.callPost.and.returnValue(answer({ result: check }));

        service.checkUserSync(settings).subscribe((value) => {
            expect(api.callPost.calls.mostRecent().args.slice(0, 2)).toEqual(['person_sync/users/check', settings]);
            expect(value).toEqual(check);
            done();
        });
    });


    it('reads the resync counts from the result, which carries no settings', (done) => {
        api.callPost.and.returnValue(answer({ result: { created: 0, edited: 1, left: [] } }));

        service.resync().subscribe((value) => {
            expect(api.callPost.calls.mostRecent().args.slice(0, 2)).toEqual(['person_sync/resync', null]);
            expect(value).toEqual({ created: 0, edited: 1, left: [] });
            done();
        });
    });


    it('switches the group sync with only its active flag', (done) => {
        api.callPut.and.returnValue(answer({ created: 0, edited: 0, left: [], result: { active: true, mappings: [] } }));

        service.updateGroupSync(true).subscribe(() => {
            expect(api.callPut.calls.mostRecent().args.slice(0, 2)).toEqual(['person_sync/groups', { active: true }]);
            done();
        });
    });


    it('maps and unmaps one user group by its id', (done) => {
        api.callPut.and.returnValue(answer({ left: [], result: { user_group_id: 9811, person_group_id: 3 } }));
        api.callDelete.and.returnValue(answer({ result: { user_group_id: 9811, person_group_id: 3 } }));

        service.mapUserGroup(9811, { type_id: 9803 }).subscribe((mapped) => {
            expect(api.callPut.calls.mostRecent().args.slice(0, 2)).toEqual(['person_sync/groups/9811', { type_id: 9803 }]);
            expect(mapped.result.person_group_id).toBe(3);

            service.unmapUserGroup(9811).subscribe((unmapped) => {
                expect(api.callDelete.calls.mostRecent().args[0]).toBe('person_sync/groups/9811');
                expect(unmapped).toEqual({ user_group_id: 9811, person_group_id: 3 });
                done();
            });
        });
    });


    it('reads the person of a user', (done) => {
        api.callGet.and.returnValue(answer({ result: { user_id: 1, person_id: null, type_id: null } }));

        service.getUserPerson(1).subscribe((value) => {
            expect(api.callGet.calls.mostRecent().args[0]).toBe('users/1/person');
            expect(value.person_id).toBeNull();
            done();
        });
    });
});
