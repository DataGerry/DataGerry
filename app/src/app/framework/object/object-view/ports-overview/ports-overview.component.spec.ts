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
import { SimpleChange, SimpleChanges } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { NgbModal } from '@ng-bootstrap/ng-bootstrap';

import { of } from 'rxjs';

import { DeleteModalService } from 'src/app/core/services/delete-modal.service';
import { ExtendableOptionCatalogService } from 'src/app/core/services/extendable-option-catalog.service';
import { FullscreenModalService } from 'src/app/core/services/fullscreen-modal.service';
import { LoaderService } from 'src/app/core/services/loader.service';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { PermissionService } from 'src/app/modules/auth/services/permission.service';
import { CmdbPort, PORT_DELETE_RIGHT, PORT_EDIT_RIGHT, PortSide } from './models/ports-overview.types';
import { PortsOverviewComponent } from './ports-overview.component';
import { PortConnectionService } from './services/port-connection.service';
import { PortService } from './services/port.service';
/* ------------------------------------------------------------------------------------------------------------------ */

describe('PortsOverviewComponent', () => {
    let component: PortsOverviewComponent;
    let portService: jasmine.SpyObj<PortService>;
    let permission: jasmine.SpyObj<PermissionService>;
    let deleteModal: jasmine.SpyObj<DeleteModalService>;
    let modalService: jasmine.SpyObj<NgbModal>;
    let portConnectionService: jasmine.SpyObj<PortConnectionService>;
    let toast: jasmine.SpyObj<ToastService>;

    const port = (publicId: number, name: string): CmdbPort => ({
        public_id: publicId,
        object_id: 20,
        side: PortSide.SINGLE,
        name,
        port_number: publicId,
        status: null,
        port_type: null,
        speed: null,
        description: null,
        author_id: 1,
        creation_time: null,
        last_edit_time: null
    });

    const objectIdChange = (objectId: number): SimpleChanges => ({
        objectId: new SimpleChange(null, objectId, true)
    });

    beforeEach(() => {
        portService = jasmine.createSpyObj<PortService>('PortService', ['getPortsOfObject', 'deletePort']);
        portConnectionService = jasmine.createSpyObj<PortConnectionService>(
            'PortConnectionService', ['getConnectionsOfObject', 'deleteConnection']);
        permission = jasmine.createSpyObj<PermissionService>('PermissionService', ['hasRight', 'hasExtendedRight']);
        deleteModal = jasmine.createSpyObj<DeleteModalService>('DeleteModalService', ['confirmDelete']);
        modalService = jasmine.createSpyObj<NgbModal>('NgbModal', ['open']);
        toast = jasmine.createSpyObj<ToastService>('ToastService', ['success', 'error']);

        const catalog = jasmine.createSpyObj<ExtendableOptionCatalogService>('Catalog', ['optionsForTypes']);
        const loader = jasmine.createSpyObj<LoaderService>(
            'LoaderService', ['show', 'hide'], { isLoading$: of(false) });

        catalog.optionsForTypes.and.returnValue(of(new Map()));
        portService.getPortsOfObject.and.returnValue(of([port(1, 'Gi0/1'), port(2, 'Gi0/2')]));
        portService.deletePort.and.returnValue(of(undefined));
        portConnectionService.getConnectionsOfObject.and.returnValue(of([]));
        portConnectionService.deleteConnection.and.returnValue(of(undefined));
        permission.hasRight.and.returnValue(true);
        permission.hasExtendedRight.and.returnValue(false);
        modalService.open.and.returnValue({ componentInstance: {}, result: Promise.resolve(false) } as any);

        TestBed.configureTestingModule({
            providers: [
                { provide: PortService, useValue: portService },
                { provide: PortConnectionService, useValue: portConnectionService },
                { provide: ExtendableOptionCatalogService, useValue: catalog },
                { provide: LoaderService, useValue: loader },
                { provide: PermissionService, useValue: permission },
                { provide: DeleteModalService, useValue: deleteModal },
                { provide: FullscreenModalService, useValue: new FullscreenModalService() },
                { provide: NgbModal, useValue: modalService },
                { provide: ToastService, useValue: toast }
            ]
        }).overrideComponent(PortsOverviewComponent, { set: { template: '' } });

        component = TestBed.createComponent(PortsOverviewComponent).componentInstance;
        component.objectId = 20;
    });

    describe('write actions', () => {
        it('are hidden while the section only lists the ports', () => {
            component.manageable = false;

            expect(component.canEdit).toBeFalse();
            expect(component.canDelete).toBeFalse();
        });

        it('follow the user\'s rights where the section may write', () => {
            component.manageable = true;
            permission.hasRight.and.callFake((right: string) => right === PORT_EDIT_RIGHT);

            expect(component.canEdit).toBeTrue();
            expect(component.canDelete).toBeFalse();
        });

        it('accept a wildcard right', () => {
            component.manageable = true;
            permission.hasRight.and.returnValue(false);
            permission.hasExtendedRight.and.callFake((right: string) => right === PORT_DELETE_RIGHT);

            expect(component.canDelete).toBeTrue();
        });
    });

    describe('deleting a port', () => {
        beforeEach(() => component.ngOnChanges(objectIdChange(20)));

        it('asks before it writes', () => {
            component.onDeletePort(component.rows[0]);

            expect(portService.deletePort).not.toHaveBeenCalled();
            expect(deleteModal.confirmDelete.calls.mostRecent().args[0].itemName).toBe('Gi0/1');
        });

        it('deletes the port and reads the list again once confirmed', () => {
            component.onDeletePort(component.rows[0]);
            deleteModal.confirmDelete.calls.mostRecent().args[0].onConfirm();

            expect(portService.deletePort).toHaveBeenCalledWith(1);
            expect(portService.getPortsOfObject).toHaveBeenCalledTimes(2);
            expect(toast.success).toHaveBeenCalled();
        });
    });

    describe('editing a port', () => {
        beforeEach(() => component.ngOnChanges(objectIdChange(20)));

        it('hands the stored port to the form, not the table row', () => {
            component.onEditPort(component.rows[1]);

            expect(modalService.open.calls.mostRecent().returnValue.componentInstance.port).toEqual(port(2, 'Gi0/2'));
        });

        it('does nothing for a row that is no longer loaded', () => {
            component.onEditPort({ ...component.rows[0], publicId: 999 });

            expect(modalService.open).not.toHaveBeenCalled();
        });
    });

    describe('paging', () => {
        it('starts a different object at the first page', () => {
            component.ngOnChanges(objectIdChange(20));
            component.onPageChange(2);

            component.objectId = 21;
            component.ngOnChanges(objectIdChange(21));

            expect(component.page).toBe(1);
        });

        it('keeps the page the user is on when the list is read again after a write', () => {
            component.pageSize = 1;
            component.ngOnChanges(objectIdChange(20));
            component.onPageChange(2);

            component.onDeletePort(component.rows[0]);
            deleteModal.confirmDelete.calls.mostRecent().args[0].onConfirm();

            expect(component.page).toBe(2);
        });
    });
});
