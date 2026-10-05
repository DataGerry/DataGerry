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
import { Subject, of, throwError } from 'rxjs';

import { LoaderService } from 'src/app/core/services/loader.service';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { CablingResponse } from '../models/cabling.types';
import { NAS_01, PP_01, SW_01, SW_GI24, mockupRing, nasExpansion } from '../testing/cabling-fixtures';
import { CablingService } from './cabling.service';
import { CablingViewStore } from './cabling-view.store';

describe('CablingViewStore', () => {
    let store: CablingViewStore;
    let cablingService: jasmine.SpyObj<CablingService>;
    let loaderService: jasmine.SpyObj<LoaderService>;
    let toastService: jasmine.SpyObj<ToastService>;

    const loaderBalance = () => loaderService.show.calls.count() - loaderService.hide.calls.count();

    beforeEach(() => {
        cablingService = jasmine.createSpyObj('CablingService', ['getObjectCabling', 'getPortCabling']);
        loaderService = jasmine.createSpyObj('LoaderService', ['show', 'hide']);
        toastService = jasmine.createSpyObj('ToastService', ['error', 'info']);

        cablingService.getObjectCabling.and.returnValue(of(mockupRing()));
        cablingService.getPortCabling.and.returnValue(of(nasExpansion()));

        TestBed.configureTestingModule({
            providers: [
                CablingViewStore,
                { provide: CablingService, useValue: cablingService },
                { provide: LoaderService, useValue: loaderService },
                { provide: ToastService, useValue: toastService }
            ]
        });

        store = TestBed.inject(CablingViewStore);
    });

    it('draws the ring of the object it is given and says so', () => {
        const loaded = jasmine.createSpy('loaded');
        store.loaded$.subscribe(loaded);

        store.load(PP_01);

        expect(cablingService.getObjectCabling).toHaveBeenCalledWith(PP_01);
        expect(store.graph().focalId).toBe(PP_01);
        expect(store.graph().nodes.size).toBe(3);
        expect(store.loaded()).toBeTrue();
        expect(loaded).toHaveBeenCalledTimes(1);
        expect(loaderBalance()).toBe(0);
    });

    it('reads nothing without an object', () => {
        store.load(null);

        expect(cablingService.getObjectCabling).not.toHaveBeenCalled();
        expect(store.graph().nodes.size).toBe(0);
    });

    it('reports a failed ring without the backend message, and still loads the next object', () => {
        cablingService.getObjectCabling.and.returnValue(throwError(() => ({ error: { message: 'Traceback …' } })));
        store.load(PP_01);

        expect(store.loadFailed()).toBeTrue();
        expect(toastService.error).toHaveBeenCalledWith('The cabling could not be loaded.');
        expect(loaderBalance()).toBe(0);

        cablingService.getObjectCabling.and.returnValue(of(mockupRing()));
        store.load(PP_01);

        expect(store.loadFailed()).toBeFalse();
        expect(store.graph().nodes.size).toBe(3);
    });

    it('drops a ring still in flight when another object is asked for', () => {
        const first = new Subject<CablingResponse>();
        cablingService.getObjectCabling.and.returnValues(first, of(mockupRing()));

        store.load(SW_01);
        store.load(PP_01);
        first.next({ focal_object_id: SW_01, nodes: [], edges: [] });

        expect(store.graph().focalId).toBe(PP_01);
        expect(loaderBalance()).toBe(0);
    });

    it('adds the object at the far end of a followed port and names it', () => {
        const revealed = jasmine.createSpy('revealed');
        store.revealed$.subscribe(revealed);
        store.load(PP_01);

        store.expandPort(SW_GI24);

        expect(cablingService.getPortCabling).toHaveBeenCalledWith(SW_GI24);
        expect(store.graph().nodes.has(NAS_01)).toBeTrue();
        expect(revealed).toHaveBeenCalledWith([NAS_01]);
        expect(store.expandingPortIds().size).toBe(0);
        expect(loaderBalance()).toBe(0);
    });

    it('asks once while the same port is still being followed', () => {
        cablingService.getPortCabling.and.returnValue(new Subject<CablingResponse>());
        store.load(PP_01);

        store.expandPort(SW_GI24);
        store.expandPort(SW_GI24);

        expect(cablingService.getPortCabling).toHaveBeenCalledTimes(1);
        expect(store.expandingPortIds().has(SW_GI24)).toBeTrue();
    });

    it('says so when a port leads nowhere, and changes nothing', () => {
        cablingService.getPortCabling.and.returnValue(of({ focal_object_id: SW_01, nodes: [], edges: [] }));
        store.load(PP_01);
        const before = store.graph();

        store.expandPort(8811);

        expect(store.graph()).toBe(before);
        expect(toastService.info).toHaveBeenCalledWith('This port leads to no other object.');
    });

    it('drops an expansion still in flight when the ring is read again', () => {
        const pending = new Subject<CablingResponse>();
        cablingService.getPortCabling.and.returnValue(pending);
        store.load(PP_01);
        store.expandPort(SW_GI24);

        store.reload();
        pending.next(nasExpansion());

        expect(store.graph().nodes.has(NAS_01)).toBeFalse();
        expect(store.expandingPortIds().size).toBe(0);
        expect(loaderBalance()).toBe(0);
    });

    it('reports a failed expansion and keeps the canvas', () => {
        cablingService.getPortCabling.and.returnValue(throwError(() => new Error('down')));
        store.load(PP_01);

        store.expandPort(SW_GI24);

        expect(toastService.error).toHaveBeenCalledWith('The cabling of this port could not be loaded.');
        expect(store.graph().nodes.size).toBe(3);
        expect(loaderBalance()).toBe(0);
    });
});
