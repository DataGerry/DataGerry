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
import { HttpResponse } from '@angular/common/http';
import { of } from 'rxjs';

import { ApiCallService } from '../../services/api-call.service';
import { AuthService } from '../../modules/auth/services/auth.service';
import { User } from '../models/user';
import { UserService } from './user.service';
/* ------------------------------------------------------------------------------------------------------------------ */

describe('UserService sync_pending', () => {

    let service: UserService;
    let api: jasmine.SpyObj<ApiCallService>;

    const user = { public_id: 11, user_name: 'anna.becker', sync_pending: true } as unknown as User;

    beforeEach(() => {
        api = jasmine.createSpyObj<ApiCallService>('ApiCallService', ['callPut', 'callPost']);
        api.callPut.and.returnValue(of(new HttpResponse({ body: { result: user } })));
        api.callPost.and.returnValue(of(new HttpResponse({ body: { raw: user } })));

        service = new UserService(api, {} as AuthService);
    });


    it('never sends sync_pending back on an update', () => {
        service.putUser(11, user).subscribe();

        const body = api.callPut.calls.mostRecent().args[1];
        expect('sync_pending' in body).toBeFalse();
        expect(body.user_name).toBe('anna.becker');
    });


    it('never sends sync_pending on a create', () => {
        service.postUser(user).subscribe();

        expect('sync_pending' in api.callPost.calls.mostRecent().args[1]).toBeFalse();
    });


    it('leaves the caller\'s user object untouched', () => {
        service.putUser(11, user).subscribe();

        expect(user.sync_pending).toBeTrue();
    });
});
