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
import { FullscreenModalService } from 'src/app/core/services/fullscreen-modal.service';
import { LoaderService } from 'src/app/core/services/loader.service';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { PermissionService } from 'src/app/modules/auth/services/permission.service';
import { CONNECTION_DELETE_RIGHT } from './models/port-connection.types';
import { PortDeviceKind } from './models/port-bulk.types';
import {
    OverviewPort,
    PORT_DELETE_RIGHT,
    PORT_EDIT_RIGHT,
    PortOverviewResponse,
    PortRow,
    PortSide
} from './models/ports-overview.types';
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

    const port = (portId: number, name: string, side = PortSide.SINGLE): OverviewPort => ({
        port_id: portId,
        side,
        port_number: portId,
        name,
        description: null,
        connected: false,
        cable: null,
        cable_connection_id: null,
        connected_port: null,
        connected_object: null,
        interface_links: [],
        status: { id: 7, label: 'Up' },
        port_type: { id: null, label: null },
        speed: { id: null, label: null }
    });

    const standard: PortOverviewResponse = {
        device_kind: PortDeviceKind.STANDARD,
        rows: [{ port: port(1, 'Gi0/1') }, { port: port(2, 'Gi0/2') }],
        total: 2
    };

    const patchPanel: PortOverviewResponse = {
        device_kind: PortDeviceKind.PATCH_PANEL,
        rows: [
            { front: port(11, 'F01', PortSide.FRONT), rear: port(12, 'R01', PortSide.REAR), paired: true },
            { front: port(13, 'F02', PortSide.FRONT), rear: null, paired: false }
        ],
        total: 2
    };

    const objectIdChange = (objectId: number): SimpleChanges => ({
        objectId: new SimpleChange(null, objectId, true)
    });

    beforeEach(() => {
        portService = jasmine.createSpyObj<PortService>('PortService', ['getPortOverview', 'deletePort']);
        portConnectionService = jasmine.createSpyObj<PortConnectionService>(
            'PortConnectionService', ['deleteConnection', 'bulkDeleteConnections']);
        permission = jasmine.createSpyObj<PermissionService>('PermissionService', ['hasRight', 'hasExtendedRight']);
        deleteModal = jasmine.createSpyObj<DeleteModalService>('DeleteModalService', ['confirmDelete']);
        modalService = jasmine.createSpyObj<NgbModal>('NgbModal', ['open']);
        toast = jasmine.createSpyObj<ToastService>('ToastService', ['success', 'error']);

        const loader = jasmine.createSpyObj<LoaderService>(
            'LoaderService', ['show', 'hide'], { isLoading$: of(false) });

        portService.getPortOverview.and.returnValue(of(standard));
        portService.deletePort.and.returnValue(of(undefined));
        portConnectionService.deleteConnection.and.returnValue(of(undefined));
        portConnectionService.bulkDeleteConnections.and.returnValue(of(undefined));
        permission.hasRight.and.returnValue(true);
        permission.hasExtendedRight.and.returnValue(false);
        modalService.open.and.returnValue({ componentInstance: {}, result: Promise.resolve(false) } as any);

        TestBed.configureTestingModule({
            providers: [
                { provide: PortService, useValue: portService },
                { provide: PortConnectionService, useValue: portConnectionService },
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
            expect(portService.getPortOverview).toHaveBeenCalledTimes(2);
            expect(toast.success).toHaveBeenCalled();
        });
    });

    describe('editing a port', () => {
        beforeEach(() => component.ngOnChanges(objectIdChange(20)));

        it('hands the form the option ids, not the labels the row shows', () => {
            component.onEditPort(component.rows[1]);

            const stored = modalService.open.calls.mostRecent().returnValue.componentInstance.port;

            expect(stored.public_id).toBe(2);
            expect(stored.object_id).toBe(20);
            expect(stored.status).toBe(7);
        });

        it('does nothing for a row that is no longer loaded', () => {
            component.onEditPort({ ...component.rows[0], publicId: 999 });

            expect(modalService.open).not.toHaveBeenCalled();
        });
    });

    describe('bulk actions', () => {
        // The connection cell is what the table row carries; a free port simply has no cable id.
        const cabled = (row: PortRow, cableConnectionId: number | null): PortRow =>
            ({ ...row, cableConnectionId });

        beforeEach(() => component.ngOnChanges(objectIdChange(20)));

        it('keeps the cabled rows of the selection apart for a disconnect', () => {
            component.onSelectedRowsChange([cabled(component.rows[0], 9720), cabled(component.rows[1], null)]);

            expect(component.selectedRows.length).toBe(2);
            expect(component.selectedConnectedRows.map((row) => row.cableConnectionId)).toEqual([9720]);
        });

        it('drops the selection once the rows are rebuilt', () => {
            component.onSelectedRowsChange([component.rows[0]]);

            component.onPageChange(1);

            expect(component.selectedRows).toEqual([]);
            expect(component.selectedConnectedRows).toEqual([]);
        });

        it('hands the whole selection to the bulk edit dialog', () => {
            component.onBulkEditPorts(component.rows);

            expect(modalService.open.calls.mostRecent().returnValue.componentInstance.ports)
                .toEqual(component.rows);
        });

        it('opens no dialog for an empty selection', () => {
            component.onBulkEditPorts([]);
            component.onBulkDeletePorts([]);

            expect(modalService.open).not.toHaveBeenCalled();
        });

        it('cuts only the cables of the selection, each of them once', async () => {
            modalService.open.and.returnValue(
                { componentInstance: {}, result: Promise.resolve('confirmed') } as any);

            component.onBulkDisconnectPorts([
                cabled(component.rows[0], 9720),
                cabled(component.rows[1], 9720)
            ]);
            await modalService.open.calls.mostRecent().returnValue.result;

            expect(portConnectionService.bulkDeleteConnections).toHaveBeenCalledWith(20, [9720]);
        });

        it('asks nothing when no selected port carries a cable', () => {
            component.onBulkDisconnectPorts([cabled(component.rows[0], null)]);

            expect(modalService.open).not.toHaveBeenCalled();
            expect(portConnectionService.bulkDeleteConnections).not.toHaveBeenCalled();
        });

        it('writes nothing while the user has not confirmed', async () => {
            component.onBulkDisconnectPorts([cabled(component.rows[0], 9720)]);
            await modalService.open.calls.mostRecent().returnValue.result;

            expect(portConnectionService.bulkDeleteConnections).not.toHaveBeenCalled();
        });

        it('gates disconnecting on the connection right, not on the port right', () => {
            component.manageable = true;
            permission.hasRight.and.callFake((right: string) => right === CONNECTION_DELETE_RIGHT);

            expect(component.canDisconnect).toBeTrue();
            expect(component.canDelete).toBeFalse();
        });
    });

    describe('device kind', () => {
        it('lists a standard device one port per row', () => {
            component.ngOnChanges(objectIdChange(20));

            expect(component.deviceKind).toBe(PortDeviceKind.STANDARD);
            expect(component.rows.map((row) => row.name)).toEqual(['Gi0/1', 'Gi0/2']);
            expect(component.panelRows).toEqual([]);
        });

        it('lists a patch panel one pairing per row', () => {
            portService.getPortOverview.and.returnValue(of(patchPanel));

            component.ngOnChanges(objectIdChange(20));

            expect(component.deviceKind).toBe(PortDeviceKind.PATCH_PANEL);
            expect(component.rows).toEqual([]);
            expect(component.panelRows.map((row) => [row.frontName, row.rearName])).toEqual([['F01', 'R01'], ['F02', null]]);
            expect(component.totalRows).toBe(2);
        });

        it('shows the empty standard table while the object has no ports', () => {
            portService.getPortOverview.and.returnValue(of({ device_kind: null, rows: [], total: 0 }));

            component.ngOnChanges(objectIdChange(20));

            expect(component.deviceKind).toBeNull();
            expect(component.rows).toEqual([]);
            expect(component.panelRows).toEqual([]);
        });

        it('selects both faces of a ticked pairing', () => {
            portService.getPortOverview.and.returnValue(of(patchPanel));
            component.ngOnChanges(objectIdChange(20));

            component.onSelectedPanelRowsChange([component.panelRows[0]]);

            expect(component.selectedRows.map((row) => row.name)).toEqual(['F01', 'R01']);
        });

        it('edits a panel port from the stored port', () => {
            portService.getPortOverview.and.returnValue(of(patchPanel));
            component.ngOnChanges(objectIdChange(20));

            component.onEditPort(component.panelRows[0].rear);

            expect(modalService.open.calls.mostRecent().returnValue.componentInstance.port.public_id).toBe(12);
        });
    });

    describe('adding ports', () => {
        it('opens the add dialog with the kind the object already is', () => {
            portService.getPortOverview.and.returnValue(of(patchPanel));
            component.ngOnChanges(objectIdChange(20));

            component.onAddPorts();

            expect(modalService.open.calls.mostRecent().returnValue.componentInstance.existingKind)
                .toBe(PortDeviceKind.PATCH_PANEL);
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
