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
import { TestBed } from '@angular/core/testing';

import { of } from 'rxjs';

import { ApiCallService } from 'src/app/services/api-call.service';
import { CmdbPort, PortPayload, PortSide } from '../models/ports-overview.types';
import { PortService } from './port.service';
/* ------------------------------------------------------------------------------------------------------------------ */

describe('PortService', () => {
    let service: PortService;
    let api: jasmine.SpyObj<ApiCallService>;

    const respond = <T>(body: T) => of(new HttpResponse<T>({ body, status: 200 }));

    const port = (overrides: Partial<CmdbPort> = {}): CmdbPort => ({
        public_id: 7,
        object_id: 20,
        side: PortSide.SINGLE,
        name: 'Gi0/1',
        port_number: 1,
        status: null,
        port_type: null,
        speed: null,
        description: null,
        author_id: 1,
        creation_time: null,
        last_edit_time: null,
        ...overrides
    });

    const payload: PortPayload = {
        object_id: 20,
        name: 'Gi0/1',
        port_number: 1,
        status: null,
        port_type: null,
        speed: null,
        description: null
    };

    beforeEach(() => {
        api = jasmine.createSpyObj<ApiCallService>('ApiCallService', ['callGet', 'callPost', 'callPut', 'callDelete']);

        TestBed.configureTestingModule({
            providers: [
                PortService,
                { provide: ApiCallService, useValue: api }
            ]
        });

        service = TestBed.inject(PortService);
    });

    describe('getPortsOfObject()', () => {
        it('reads the ports of one object', () => {
            api.callGet.and.returnValue(respond([port()]));

            let received: CmdbPort[];
            service.getPortsOfObject(20).subscribe((ports) => (received = ports));

            expect(api.callGet.calls.mostRecent().args[0]).toBe('ports/object/20');
            expect(received).toEqual([port()]);
        });

        it('treats an object without ports as empty, not as a failure', () => {
            api.callGet.and.returnValue(respond(null));

            let received: CmdbPort[];
            service.getPortsOfObject(20).subscribe((ports) => (received = ports));

            expect(received).toEqual([]);
        });
    });

    describe('createPort()', () => {
        it('posts the payload and unwraps the stored port', () => {
            api.callPost.and.returnValue(respond({ result_id: 7, raw: port() }));

            let received: CmdbPort;
            service.createPort(payload).subscribe((created) => (received = created));

            expect(api.callPost.calls.mostRecent().args[0]).toBe('ports/');
            expect(api.callPost.calls.mostRecent().args[1]).toBe(payload);
            expect(received).toEqual(port());
        });
    });

    describe('updatePort()', () => {
        it('puts the payload to the addressed port and unwraps its new data', () => {
            const edited = port({ name: 'Gi0/2' });
            api.callPut.and.returnValue(respond({ result: edited }));

            let received: CmdbPort;
            service.updatePort(7, { ...payload, name: 'Gi0/2' }).subscribe((updated) => (received = updated));

            expect(api.callPut.calls.mostRecent().args[0]).toBe('ports/7');
            expect(api.callPut.calls.mostRecent().args[1]).toEqual({ ...payload, name: 'Gi0/2' });
            expect(received).toEqual(edited);
        });
    });

    describe('deletePort()', () => {
        it('deletes the addressed port', () => {
            api.callDelete.and.returnValue(respond({ raw: port() }));

            let completed = false;
            service.deletePort(7).subscribe(() => (completed = true));

            expect(api.callDelete.calls.mostRecent().args[0]).toBe('ports/7');
            expect(completed).toBeTrue();
        });
    });
});
