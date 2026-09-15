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

import { CoreWarningModalComponent } from 'src/app/core/components/dialog/core-warning-modal/core-warning-modal.component';
import { FullscreenModalService } from 'src/app/core/services/fullscreen-modal.service';
import { LoaderService } from 'src/app/core/services/loader.service';
import { RenderResult } from 'src/app/framework/models/cmdb-render';
import { SpecialType } from 'src/app/framework/models/special-type';
import { LocationService } from 'src/app/framework/services/location.service';
import { ObjectService } from 'src/app/framework/services/object.service';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { PremiumFeatureService } from 'src/app/settings/license-management/premium-feature/premium-feature.service';

import { ConnectionEndpointService } from '../../object-view/ports-overview/services/connection-endpoint.service';
import { PortConnectionService } from '../../object-view/ports-overview/services/port-connection.service';
import { ObjectDeleteModalComponent } from '../../modals/object-delete-modal/object-delete-modal.component';
import { ObjectTableActionsComponent } from './object-table-actions.component';
/* ------------------------------------------------------------------------------------------------------------------ */

/** The row the actions belong to; a cable only differs in its special type. */
function row(specialType?: SpecialType): RenderResult {
    return {
        object_information: { object_id: 9513, special_type: specialType, active: true },
        summary_line: 'Cat6 patch',
        type_information: { type_id: 5, type_label: 'Cable', active: true }
    } as unknown as RenderResult;
}


describe('ObjectTableActionsComponent delete', () => {

    let component: ObjectTableActionsComponent;
    let locationService: jasmine.SpyObj<LocationService>;
    let objectService: jasmine.SpyObj<ObjectService>;
    let modalService: jasmine.SpyObj<NgbModal>;
    let connectionService: jasmine.SpyObj<PortConnectionService>;
    let endpointService: jasmine.SpyObj<ConnectionEndpointService>;

    /** Which component each modal call opened, in order. */
    function openedModals(): unknown[] {
        return modalService.open.calls.allArgs().map((args) => args[0]);
    }

    beforeEach(() => {
        locationService = jasmine.createSpyObj<LocationService>('LocationService', ['getChildren']);
        objectService = jasmine.createSpyObj<ObjectService>('ObjectService', ['openLocationModalComponent']);
        modalService = jasmine.createSpyObj<NgbModal>('NgbModal', ['open']);
        connectionService = jasmine.createSpyObj<PortConnectionService>('PortConnectionService', ['getCableUsage']);
        endpointService = jasmine.createSpyObj<ConnectionEndpointService>('ConnectionEndpointService', ['endpointOf']);

        const premium = jasmine.createSpyObj<PremiumFeatureService>(
            'PremiumFeatureService', ['isAvailable', 'promptUpgrade']);
        const loader = jasmine.createSpyObj<LoaderService>('LoaderService', ['show', 'hide'], { isLoading$: of(false) });

        locationService.getChildren.and.returnValue(of([]));
        modalService.open.and.returnValue({ componentInstance: {}, result: Promise.resolve(0), close: () => undefined } as any);
        // ngOnDestroy closes whatever modal is open, so every stub answers to close().
        objectService.openLocationModalComponent.and.returnValue({ result: Promise.resolve(''), close: () => undefined } as any);
        endpointService.endpointOf.and.callFake((portId: number) => of({
            portId, portName: `Port ${ portId }`, sideLabel: '', objectId: 1, objectLabel: 'Switch-A'
        }));
        premium.isAvailable.and.returnValue(true);

        TestBed.configureTestingModule({
            providers: [
                { provide: LocationService, useValue: locationService },
                { provide: ObjectService, useValue: objectService },
                { provide: NgbModal, useValue: modalService },
                { provide: ToastService, useValue: jasmine.createSpyObj<ToastService>('ToastService', ['error']) },
                { provide: PremiumFeatureService, useValue: premium },
                { provide: PortConnectionService, useValue: connectionService },
                { provide: ConnectionEndpointService, useValue: endpointService },
                { provide: LoaderService, useValue: loader },
                { provide: FullscreenModalService, useValue: new FullscreenModalService() }
            ]
        }).overrideComponent(ObjectTableActionsComponent, { set: { template: '' } });

        component = TestBed.createComponent(ObjectTableActionsComponent).componentInstance;
        component.publicID = 9513;
    });

    describe('an ordinary object', () => {
        beforeEach(() => component.result = row());

        it('is not prechecked for a cable at all', () => {
            component.handleDelete(9513);

            expect(connectionService.getCableUsage).not.toHaveBeenCalled();
        });

        it('goes straight to its delete confirmation', () => {
            component.handleDelete(9513);

            expect(openedModals()).toEqual([ObjectDeleteModalComponent]);
        });

        it('still asks about its child locations first', () => {
            locationService.getChildren.and.returnValue(of([row()]));

            component.handleDelete(9513);

            expect(objectService.openLocationModalComponent).toHaveBeenCalled();
            expect(openedModals()).toEqual([]);
        });
    });

    describe('a cable object', () => {
        beforeEach(() => component.result = row(SpecialType.CABLE));

        it('is deleted like any other object while no connection uses it', () => {
            connectionService.getCableUsage.and.returnValue(of({ in_use: false, connection_id: null, endpoints: null }));

            component.handleDelete(9513);

            expect(connectionService.getCableUsage).toHaveBeenCalledWith(9513);
            expect(openedModals()).toEqual([ObjectDeleteModalComponent]);
        });

        it('is refused without ever offering the delete while a connection uses it', () => {
            connectionService.getCableUsage.and.returnValue(of({
                in_use: true, connection_id: 1, endpoints: [9521, 9522]
            }));

            component.handleDelete(9513);

            expect(openedModals()).toEqual([CoreWarningModalComponent]);
            expect(locationService.getChildren).not.toHaveBeenCalled();
        });

        it('falls back to the normal delete when the precheck cannot be read', () => {
            connectionService.getCableUsage.and.returnValue(throwError(() => new Error('403')));

            component.handleDelete(9513);

            expect(openedModals()).toEqual([ObjectDeleteModalComponent]);
        });
    });
});
