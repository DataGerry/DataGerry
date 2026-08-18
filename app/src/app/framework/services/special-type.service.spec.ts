import { TestBed } from '@angular/core/testing';
import { HttpParams, HttpResponse } from '@angular/common/http';
import { of, throwError } from 'rxjs';

import { SpecialTypeService } from './special-type.service';
import { ApiCallService } from '../../services/api-call.service';

describe('SpecialTypeService', () => {
    let service: SpecialTypeService;
    let api: jasmine.SpyObj<ApiCallService>;

    const respond = <T>(body: T) => of(new HttpResponse<T>({ body, status: 200 }));

    const lastParams = (callIndex = 0): HttpParams =>
        api.callGet.calls.argsFor(callIndex)[1].params;

    beforeEach(() => {
        api = jasmine.createSpyObj<ApiCallService>('ApiCallService', ['callGet']);

        TestBed.configureTestingModule({
            providers: [
                SpecialTypeService,
                { provide: ApiCallService, useValue: api }
            ]
        });

        service = TestBed.inject(SpecialTypeService);
    });

    describe('getAvailableSpecialTypes()', () => {
        it('asks for the unused special types only', () => {
            api.callGet.and.returnValue(respond({ result: { RACK: 'Rack View - Rack class' } }));

            let received: Record<string, string>;
            service.getAvailableSpecialTypes().subscribe((types) => (received = types));

            expect(api.callGet.calls.mostRecent().args[0]).toBe('special_types/');
            expect(lastParams().get('available')).toBe('true');
            expect(received).toEqual({ RACK: 'Rack View - Rack class' });
        });

        it('is not answered from the full-list cache', () => {
            api.callGet.and.returnValue(respond({ result: {} }));

            service.getAllSpecialTypes().subscribe();
            service.getAvailableSpecialTypes().subscribe();

            expect(api.callGet).toHaveBeenCalledTimes(2);
            expect(lastParams(0).has('available')).toBeFalse();
            expect(lastParams(1).get('available')).toBe('true');
        });
    });

    describe('getAllSpecialTypes()', () => {
        it('requests every special type and unwraps the response body', () => {
            const allTypes = { SUBNET: 'IPAM - Subnet class', RACK: 'Rack View - Rack class' };
            api.callGet.and.returnValue(respond({ result: allTypes }));

            let received: Record<string, string>;
            service.getAllSpecialTypes().subscribe((types) => (received = types));

            expect(api.callGet.calls.mostRecent().args[0]).toBe('special_types/');
            expect(lastParams().has('available')).toBeFalse();
            expect(received).toEqual(allTypes);
        });

        it('falls back to an empty map when the backend sends no body', () => {
            api.callGet.and.returnValue(respond(null));

            let received: Record<string, string>;
            service.getAllSpecialTypes().subscribe((types) => (received = types));

            expect(received).toEqual({});
        });

        it('caches the static list across callers', () => {
            api.callGet.and.returnValue(respond({ result: { VLAN: 'IPAM - VLAN class' } }));

            service.getAllSpecialTypes().subscribe();
            service.getAllSpecialTypes().subscribe();

            expect(api.callGet).toHaveBeenCalledTimes(1);
        });

        it('does not cache a failure, so the next caller retries', () => {
            api.callGet.and.returnValue(throwError(() => new Error('offline')));

            let firstError: Error;
            service.getAllSpecialTypes().subscribe({ error: (error) => (firstError = error) });
            expect(firstError.message).toBe('offline');

            api.callGet.and.returnValue(respond({ result: { VLAN: 'IPAM - VLAN class' } }));

            let received: Record<string, string>;
            service.getAllSpecialTypes().subscribe((types) => (received = types));

            expect(api.callGet).toHaveBeenCalledTimes(2);
            expect(received).toEqual({ VLAN: 'IPAM - VLAN class' });
        });
    });
});
