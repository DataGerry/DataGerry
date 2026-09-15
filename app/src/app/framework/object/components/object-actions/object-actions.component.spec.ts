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
import { Router } from '@angular/router';
import { NgbModal } from '@ng-bootstrap/ng-bootstrap';

import { of, throwError } from 'rxjs';

import { CoreWarningModalComponent } from 'src/app/core/components/dialog/core-warning-modal/core-warning-modal.component';
import { FullscreenModalService } from 'src/app/core/services/fullscreen-modal.service';
import { LoaderService } from 'src/app/core/services/loader.service';
import { RenderResult } from 'src/app/framework/models/cmdb-render';
import { SpecialType } from 'src/app/framework/models/special-type';
import { LocationService } from 'src/app/framework/services/location.service';
import { ObjectService } from 'src/app/framework/services/object.service';
import { SidebarService } from 'src/app/layout/services/sidebar.service';
import { ToastService } from 'src/app/layout/toast/toast.service';

import { ConnectionEndpointService } from '../../object-view/ports-overview/services/connection-endpoint.service';
import { PortConnectionService } from '../../object-view/ports-overview/services/port-connection.service';
import { ObjectActionsComponent } from './object-actions.component';
/* ------------------------------------------------------------------------------------------------------------------ */

function renderResult(specialType?: SpecialType): RenderResult {
    return {
        object_information: { object_id: 9513, special_type: specialType, active: true },
        summary_line: 'Cat6 patch',
        type_information: { type_id: 5, type_label: 'Cable', active: true }
    } as unknown as RenderResult;
}


describe('ObjectActionsComponent delete', () => {

    let component: ObjectActionsComponent;
    let locationService: jasmine.SpyObj<LocationService>;
    let objectService: jasmine.SpyObj<ObjectService>;
    let modalService: jasmine.SpyObj<NgbModal>;
    let connectionService: jasmine.SpyObj<PortConnectionService>;

    beforeEach(() => {
        locationService = jasmine.createSpyObj<LocationService>('LocationService', ['getChildren']);
        objectService = jasmine.createSpyObj<ObjectService>(
            'ObjectService', ['openModalComponent', 'openLocationModalComponent', 'deleteObject']);
        modalService = jasmine.createSpyObj<NgbModal>('NgbModal', ['open']);
        connectionService = jasmine.createSpyObj<PortConnectionService>('PortConnectionService', ['getCableUsage']);

        const endpointService = jasmine.createSpyObj<ConnectionEndpointService>(
            'ConnectionEndpointService', ['endpointOf']);
        const loader = jasmine.createSpyObj<LoaderService>('LoaderService', ['show', 'hide'], { isLoading$: of(false) });

        locationService.getChildren.and.returnValue(of([]));
        // ngOnDestroy closes whatever modal is open, so every stub answers to close().
        objectService.openModalComponent.and.returnValue({ result: Promise.resolve(false), close: () => undefined } as any);
        objectService.openLocationModalComponent.and.returnValue({ result: Promise.resolve(''), close: () => undefined } as any);
        modalService.open.and.returnValue(
            { componentInstance: {}, result: Promise.resolve(0), close: () => undefined } as any);
        endpointService.endpointOf.and.callFake((portId: number) => of({
            portId, portName: `Port ${ portId }`, sideLabel: '', objectId: 1, objectLabel: 'Switch-A'
        }));

        TestBed.configureTestingModule({
            providers: [
                { provide: LocationService, useValue: locationService },
                { provide: ObjectService, useValue: objectService },
                { provide: NgbModal, useValue: modalService },
                { provide: SidebarService, useValue: jasmine.createSpyObj<SidebarService>('SidebarService', ['updateTypeCounter']) },
                { provide: ToastService, useValue: jasmine.createSpyObj<ToastService>('ToastService', ['success', 'error']) },
                { provide: Router, useValue: jasmine.createSpyObj<Router>('Router', ['navigate']) },
                { provide: PortConnectionService, useValue: connectionService },
                { provide: ConnectionEndpointService, useValue: endpointService },
                { provide: LoaderService, useValue: loader },
                { provide: FullscreenModalService, useValue: new FullscreenModalService() }
            ]
        }).overrideComponent(ObjectActionsComponent, { set: { template: '' } });

        component = TestBed.createComponent(ObjectActionsComponent).componentInstance;
    });

    it('opens the delete confirmation of an ordinary object without asking about cables', () => {
        component.renderResult = renderResult();

        component.handleDelete(9513);

        expect(connectionService.getCableUsage).not.toHaveBeenCalled();
        expect(objectService.openModalComponent).toHaveBeenCalled();
    });

    it('opens it for a cable no connection uses', () => {
        component.renderResult = renderResult(SpecialType.CABLE);
        connectionService.getCableUsage.and.returnValue(of({ in_use: false, connection_id: null, endpoints: null }));

        component.handleDelete(9513);

        expect(objectService.openModalComponent).toHaveBeenCalled();
        expect(modalService.open).not.toHaveBeenCalled();
    });

    it('refuses a cable in use instead of confirming the delete', () => {
        component.renderResult = renderResult(SpecialType.CABLE);
        connectionService.getCableUsage.and.returnValue(of({
            in_use: true, connection_id: 1, endpoints: [9521, 9522]
        }));

        component.handleDelete(9513);

        expect(modalService.open).toHaveBeenCalledWith(CoreWarningModalComponent, jasmine.anything());
        expect(objectService.openModalComponent).not.toHaveBeenCalled();
    });

    it('confirms the delete as before when the precheck cannot be read', () => {
        component.renderResult = renderResult(SpecialType.CABLE);
        connectionService.getCableUsage.and.returnValue(throwError(() => new Error('403')));

        component.handleDelete(9513);

        expect(objectService.openModalComponent).toHaveBeenCalled();
    });
});
