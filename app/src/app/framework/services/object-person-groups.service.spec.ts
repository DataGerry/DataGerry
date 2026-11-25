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
import { PersonSelection } from '../models/person-selector';
import { ObjectPersonGroupsService } from './object-person-groups.service';
/* ------------------------------------------------------------------------------------------------------------------ */

const GROUP: PersonSelection = {
    object_id: 3,
    type_id: 9803,
    type_label: 'Person group',
    kind: 'PERSON_GROUP',
    label: 'Field Service',
    active: true,
    system_ref: { kind: 'user_group', id: 9811 }
};

function answer(body: unknown) {
    return of(new HttpResponse({ body, status: 200 }));
}


describe('ObjectPersonGroupsService', () => {

    let service: ObjectPersonGroupsService;
    let api: jasmine.SpyObj<ApiCallService>;

    beforeEach(() => {
        api = jasmine.createSpyObj<ApiCallService>('ApiCallService', ['callGet', 'callPatch']);

        TestBed.configureTestingModule({ providers: [{ provide: ApiCallService, useValue: api }] });
        service = TestBed.inject(ObjectPersonGroupsService);
    });


    it('reads the bare list the backend answers', (done) => {
        api.callGet.and.returnValue(answer([GROUP]));

        service.getPersonGroups(2).subscribe((groups) => {
            expect(api.callGet.calls.mostRecent().args[0]).toBe('objects/2/person_groups');
            expect(groups).toEqual([GROUP]);
            done();
        });
    });


    it('also reads a wrapped answer', (done) => {
        api.callGet.and.returnValue(answer({ results: [GROUP] }));

        service.getPersonGroups(2).subscribe((groups) => {
            expect(groups).toEqual([GROUP]);
            done();
        });
    });


    it('answers no groups for an empty body', (done) => {
        api.callGet.and.returnValue(answer(null));

        service.getPersonGroups(2).subscribe((groups) => {
            expect(groups).toEqual([]);
            done();
        });
    });


    it('sends add / remove in one patch and reads the groups afterwards', (done) => {
        api.callPatch.and.returnValue(answer([GROUP]));

        service.changePersonGroups(2, { add: [3], remove: [9821] }).subscribe((changed) => {
            expect(api.callPatch.calls.mostRecent().args.slice(0, 2))
                .toEqual(['objects/2/person_groups', { add: [3], remove: [9821] }]);
            expect(changed).toEqual({ results: [GROUP], failed: [] });
            done();
        });
    });
});
