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

import { NgbModal } from '@ng-bootstrap/ng-bootstrap';

import { of, throwError } from 'rxjs';

import { FullscreenModalService } from 'src/app/core/services/fullscreen-modal.service';
import { LoaderService } from 'src/app/core/services/loader.service';
import { RenderResult } from 'src/app/framework/models/cmdb-render';
import { SpecialType } from 'src/app/framework/models/special-type';

import { ConnectionEndpoint } from '../models/port-connection.types';
import { CableDeleteGuardService } from './cable-delete-guard.service';
import { ConnectionEndpointService } from './connection-endpoint.service';
import { PortConnectionService } from './port-connection.service';
/* ------------------------------------------------------------------------------------------------------------------ */

function renderResult(specialType?: SpecialType): RenderResult {
    return {
        object_information: { object_id: 9513, special_type: specialType },
        summary_line: 'Cat6 patch',
        type_information: { type_label: 'Cable' }
    } as unknown as RenderResult;
}


function endpoint(portId: number, portName: string, objectLabel: string): ConnectionEndpoint {
    return { portId, portName, sideLabel: 'Front', objectId: 1, objectLabel };
}


describe('CableDeleteGuardService', () => {

    let service: CableDeleteGuardService;
    let connectionService: jasmine.SpyObj<PortConnectionService>;
    let endpointService: jasmine.SpyObj<ConnectionEndpointService>;
    let loaderService: jasmine.SpyObj<LoaderService>;
    let modalService: jasmine.SpyObj<NgbModal>;
    let modalInstance: Record<string, unknown>;

    beforeEach(() => {
        connectionService = jasmine.createSpyObj<PortConnectionService>('PortConnectionService', ['getCableUsage']);
        endpointService = jasmine.createSpyObj<ConnectionEndpointService>('ConnectionEndpointService', ['endpointOf']);
        loaderService = jasmine.createSpyObj<LoaderService>('LoaderService', ['show', 'hide']);
        modalService = jasmine.createSpyObj<NgbModal>('NgbModal', ['open']);

        modalInstance = {};
        modalService.open.and.returnValue({ componentInstance: modalInstance } as any);

        endpointService.endpointOf.and.callFake((portId: number) => of(
            portId === 9521 ? endpoint(9521, 'Port 1', 'Switch-A') : endpoint(9522, 'Port 24', 'Panel-B')
        ));

        TestBed.configureTestingModule({
            providers: [
                CableDeleteGuardService,
                { provide: PortConnectionService, useValue: connectionService },
                { provide: ConnectionEndpointService, useValue: endpointService },
                { provide: LoaderService, useValue: loaderService },
                { provide: NgbModal, useValue: modalService },
                FullscreenModalService
            ]
        });

        service = TestBed.inject(CableDeleteGuardService);
    });

    it('does not ask about an object that is not a cable', () => {
        let deletable: boolean | undefined;
        service.ensureDeletable(renderResult()).subscribe((answer) => deletable = answer);

        expect(connectionService.getCableUsage).not.toHaveBeenCalled();
        expect(deletable).toBeTrue();
    });

    it('lets a free cable through to its delete dialog', () => {
        connectionService.getCableUsage.and.returnValue(of({ in_use: false, connection_id: null, endpoints: null }));

        let deletable: boolean | undefined;
        service.ensureDeletable(renderResult(SpecialType.CABLE)).subscribe((answer) => deletable = answer);

        expect(connectionService.getCableUsage).toHaveBeenCalledWith(9513);
        expect(deletable).toBeTrue();
        expect(modalService.open).not.toHaveBeenCalled();
    });

    it('refuses a cable in use and names both ends of its connection', () => {
        connectionService.getCableUsage.and.returnValue(of({
            in_use: true,
            connection_id: 1,
            endpoints: [9521, 9522]
        }));

        let deletable: boolean | undefined;
        service.ensureDeletable(renderResult(SpecialType.CABLE)).subscribe((answer) => deletable = answer);

        expect(deletable).toBeFalse();
        expect(modalService.open).toHaveBeenCalledTimes(1);
        expect(modalInstance['title']).toBe('Cable is still in use');
        expect(modalInstance['message'] as string).toContain('Port 1 (Front) - Switch-A');
        expect(modalInstance['message'] as string).toContain('Port 24 (Front) - Panel-B');
        expect(modalInstance['message'] as string).toContain('cannot be deleted');
    });

    it('names the connection when its ports cannot be read', () => {
        connectionService.getCableUsage.and.returnValue(of({ in_use: true, connection_id: 7, endpoints: null }));

        service.ensureDeletable(renderResult(SpecialType.CABLE)).subscribe();

        expect(endpointService.endpointOf).not.toHaveBeenCalled();
        expect(modalInstance['message'] as string).toContain('connection #7');
    });

    it('lets the delete through when the precheck itself fails, leaving the route to refuse it', () => {
        connectionService.getCableUsage.and.returnValue(throwError(() => new Error('403')));

        let deletable: boolean | undefined;
        service.ensureDeletable(renderResult(SpecialType.CABLE)).subscribe((answer) => deletable = answer);

        expect(deletable).toBeTrue();
        expect(modalService.open).not.toHaveBeenCalled();
    });

    it('shows the loader only while it waits, and hides it on every outcome', () => {
        connectionService.getCableUsage.and.returnValue(of({ in_use: false, connection_id: null, endpoints: null }));

        const pending = service.ensureDeletable(renderResult(SpecialType.CABLE));
        expect(loaderService.show).not.toHaveBeenCalled();

        pending.subscribe();
        expect(loaderService.show).toHaveBeenCalledTimes(1);
        expect(loaderService.hide).toHaveBeenCalledTimes(1);
    });
});
