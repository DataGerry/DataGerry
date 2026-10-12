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
import { HttpParams } from '@angular/common/http';
import { of } from 'rxjs';

import { ApiCallService } from 'src/app/services/api-call.service';
import { PersonRelationsService } from './person-relations.service';
import { PersonCandidate, PersonRefKind } from '../models/person.model';

const respond = (body: unknown) => of({ body });

const ALICE: PersonCandidate = { ref_type: 'PERSON', id: 11, label: 'Alice', type_id: 3 };
const OPS: PersonCandidate = { ref_type: 'PERSON_GROUP', id: 21, label: 'Ops', type_id: 4 };

describe('PersonRelationsService', () => {
    let service: PersonRelationsService;
    let api: jasmine.SpyObj<ApiCallService>;

    const lastParams = (): HttpParams => api.callGet.calls.mostRecent().args[1].params as HttpParams;

    beforeEach(() => {
        api = jasmine.createSpyObj<ApiCallService>('ApiCallService', ['callGet', 'callPost', 'callDelete']);

        TestBed.configureTestingModule({
            providers: [
                PersonRelationsService,
                { provide: ApiCallService, useValue: api }
            ]
        });

        service = TestBed.inject(PersonRelationsService);
    });

    it('reads the person types and defaults a missing one to null', () => {
        api.callGet.and.returnValue(respond({ PERSON: 7 }));

        let received;
        service.getTypes().subscribe(types => received = types);

        expect(api.callGet.calls.mostRecent().args[0]).toBe('person_relations/types');
        expect(received).toEqual({ PERSON: 7, PERSON_GROUP: null });
    });

    it('asks for the candidates of a kind and shares the list between callers', () => {
        api.callGet.and.returnValue(respond([ALICE]));

        let received: Array<PersonCandidate>;
        service.getCandidates(PersonRefKind.PERSON).subscribe(candidates => received = candidates);
        service.getCandidates(PersonRefKind.PERSON).subscribe();

        expect(api.callGet).toHaveBeenCalledTimes(1);
        expect(api.callGet.calls.mostRecent().args[0]).toBe('person_relations/candidates');
        expect(lastParams().get('kind')).toBe('PERSON');
        expect(received).toEqual([ALICE]);
    });

    it('bypasses the shared list on refresh', () => {
        api.callGet.and.returnValue(respond([ALICE]));

        service.getCandidates(PersonRefKind.BOTH).subscribe();
        service.getCandidates(PersonRefKind.BOTH, true).subscribe();

        expect(api.callGet).toHaveBeenCalledTimes(2);
    });

    it('tolerates a result envelope', () => {
        api.callGet.and.returnValue(respond({ result: [OPS] }));

        let received: Array<PersonCandidate>;
        service.getCandidates(PersonRefKind.PERSON_GROUP).subscribe(candidates => received = candidates);

        expect(received).toEqual([OPS]);
    });

    it('resolves stored selections by key', () => {
        api.callGet.and.returnValue(respond([ALICE, OPS]));

        let received: Map<string, PersonCandidate>;
        service.resolveSelections([{ ref_type: 'PERSON_GROUP', id: 21 }]).subscribe(byKey => received = byKey);

        expect(received.get('PERSON_GROUP:21')).toEqual(OPS);
    });

    it('fills the lists of a relations payload', () => {
        api.callGet.and.returnValue(respond({ ref_type: 'PERSON', memberships: [OPS] }));

        let received;
        service.getRelations(11).subscribe(relations => received = relations);

        expect(api.callGet.calls.mostRecent().args[0]).toBe('person_relations/11');
        expect(received).toEqual({ ref_type: 'PERSON', memberships: [OPS], members: [], assignments: [] });
    });

    it('adds and removes members on the group and drops the candidate cache', () => {
        api.callGet.and.returnValue(respond([ALICE]));
        api.callPost.and.returnValue(respond({ ref_type: 'PERSON_GROUP', members: [ALICE] }));
        api.callDelete.and.returnValue(respond({ ref_type: 'PERSON_GROUP', members: [] }));

        service.getCandidates(PersonRefKind.PERSON).subscribe();
        service.addMember(21, 11).subscribe();

        expect(api.callPost.calls.mostRecent().args[0]).toBe('person_relations/21/members');
        expect(api.callPost.calls.mostRecent().args[1]).toEqual({ person_id: 11 });

        service.removeMember(21, 11).subscribe();
        expect(api.callDelete.calls.mostRecent().args[0]).toBe('person_relations/21/members/11');

        service.getCandidates(PersonRefKind.PERSON).subscribe();
        expect(api.callGet).toHaveBeenCalledTimes(2);
    });
});
