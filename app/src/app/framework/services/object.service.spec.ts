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
import { HttpParams, HttpResponse } from '@angular/common/http';
import { TestBed } from '@angular/core/testing';

import { NgbModal } from '@ng-bootstrap/ng-bootstrap';
import { of } from 'rxjs';

import { ApiCallService } from 'src/app/services/api-call.service';
import { UserService } from 'src/app/management/services/user.service';
import { CmdbObject } from '../models/cmdb-object';
import { ObjectService } from './object.service';
/* ------------------------------------------------------------------------------------------------------------------ */

describe('ObjectService', () => {
    let service: ObjectService;
    let api: jasmine.SpyObj<ApiCallService>;

    const sentParams = (): HttpParams => api.callPost.calls.mostRecent().args[2].params;

    beforeEach(() => {
        api = jasmine.createSpyObj<ApiCallService>('ApiCallService', ['callGet', 'callPost']);
        api.callPost.and.returnValue(of(new HttpResponse({ body: 42, status: 200 })));
        api.callGet.and.returnValue(of(new HttpResponse({ body: 0, status: 200 })));

        TestBed.configureTestingModule({
            providers: [
                ObjectService,
                { provide: ApiCallService, useValue: api },
                { provide: NgbModal, useValue: {} },
                { provide: UserService, useValue: {} }
            ]
        });

        service = TestBed.inject(ObjectService);
    });

    describe('postObject()', () => {
        it('creates the object and answers its public_id', () => {
            let created: number | undefined;

            service.postObject(new CmdbObject()).subscribe(id => created = id);

            expect(api.callPost.calls.mostRecent().args[0]).toBe('objects/');
            expect(created).toBe(42);
        });


        it('sends no clone_ports_from unless asked to', () => {
            service.postObject(new CmdbObject()).subscribe();

            expect(sentParams().has('clone_ports_from')).toBeFalse();
        });


        it('asks the backend to clone the ports of the source object', () => {
            service.postObject(new CmdbObject(), 98312).subscribe();

            expect(sentParams().get('clone_ports_from')).toBe('98312');
        });


        it('keeps the flag off the shared options', () => {
            service.postObject(new CmdbObject(), 98312).subscribe();

            expect(api.callPost.calls.mostRecent().args[2]).not.toBe(service.options);
        });
    });
});
