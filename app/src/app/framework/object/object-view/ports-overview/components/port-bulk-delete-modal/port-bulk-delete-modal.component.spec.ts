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
import { NgbActiveModal } from '@ng-bootstrap/ng-bootstrap';

import { of, throwError } from 'rxjs';

import { LoaderService } from 'src/app/core/services/loader.service';
import { ToastService } from 'src/app/layout/toast/toast.service';

import { PortBulkDeletePreview } from '../../models/port-bulk.types';
import { PortSelection, PortSide } from '../../models/ports-overview.types';
import { PortService } from '../../services/port.service';
import { PortBulkDeleteModalComponent } from './port-bulk-delete-modal.component';
/* ------------------------------------------------------------------------------------------------------------------ */

describe('PortBulkDeleteModalComponent', () => {
    let component: PortBulkDeleteModalComponent;
    let portService: jasmine.SpyObj<PortService>;
    let toast: jasmine.SpyObj<ToastService>;
    let activeModal: jasmine.SpyObj<NgbActiveModal>;

    const ports: PortSelection[] = [
        { publicId: 9710, name: '1' },
        { publicId: 9712, name: '2' }
    ];

    const preview: PortBulkDeletePreview = {
        ports: [
            {
                port_id: 9710,
                name: '1',
                side: PortSide.FRONT,
                connection_ids: [9720, 9721],
                interface_link_ids: [9730]
            },
            { port_id: 9712, name: '2', side: PortSide.FRONT, connection_ids: [], interface_link_ids: [] }
        ],
        port_ids: [9710, 9712],
        connection_ids: [9720, 9721],
        interface_link_ids: [9730]
    };

    beforeEach(() => {
        portService = jasmine.createSpyObj<PortService>('PortService', ['previewBulkDelete', 'bulkDeletePorts']);
        toast = jasmine.createSpyObj<ToastService>('ToastService', ['success', 'error']);
        activeModal = jasmine.createSpyObj<NgbActiveModal>('NgbActiveModal', ['close', 'dismiss']);

        const loader = jasmine.createSpyObj<LoaderService>('LoaderService', ['show', 'hide'], { isLoading$: of(false) });

        portService.previewBulkDelete.and.returnValue(of(preview));
        portService.bulkDeletePorts.and.returnValue(of({
            deleted: 2,
            port_ids: [9710, 9712],
            connection_ids: [9720, 9721],
            interface_link_ids: [9730]
        }));

        TestBed.configureTestingModule({
            providers: [
                { provide: PortService, useValue: portService },
                { provide: LoaderService, useValue: loader },
                { provide: ToastService, useValue: toast },
                { provide: NgbActiveModal, useValue: activeModal }
            ]
        }).overrideComponent(PortBulkDeleteModalComponent, { set: { template: '' } });

        component = TestBed.createComponent(PortBulkDeleteModalComponent).componentInstance;
        component.objectId = 20;
        component.ports = ports;
    });

    describe('the preview', () => {
        it('counts the distinct ids, not the per-port ones', () => {
            component.ngOnInit();

            expect(component.connectionCount).toBe(2);
            expect(component.interfaceLinkCount).toBe(1);
            expect(component.impactMessage)
                .toBe('2 connection(s) and 1 interface link(s) are deleted with these ports.');
        });

        it('lists only the ports that take something with them', () => {
            component.ngOnInit();

            expect(component.affectedRows).toEqual([{ name: '1', connections: 2, interfaceLinks: 1 }]);
        });

        it('says so when the ports carry nothing', () => {
            portService.previewBulkDelete.and.returnValue(of({
                ports: [], port_ids: [9710, 9712], connection_ids: [], interface_link_ids: []
            }));
            component.ngOnInit();

            expect(component.impactMessage).toBe('These ports carry no connection and no interface link.');
        });

        it('does not block the delete when it cannot be read', () => {
            portService.previewBulkDelete.and.returnValue(throwError(() => new Error('boom')));
            component.ngOnInit();

            expect(component.previewLoaded).toBeTrue();
            expect(component.previewFailed).toBeTrue();
            expect(component.impactMessage).toContain('could not be read');
        });
    });

    describe('the delete', () => {
        beforeEach(() => component.ngOnInit());

        it('sends every selected port and closes once they are gone', () => {
            component.onConfirm();

            expect(portService.bulkDeletePorts).toHaveBeenCalledWith(20, [9710, 9712]);
            expect(toast.success).toHaveBeenCalledWith('2 ports and 2 connection(s) were successfully deleted!');
            expect(activeModal.close).toHaveBeenCalledWith(true);
        });

        it('stays open and reports when it fails', () => {
            portService.bulkDeletePorts.and.returnValue(throwError(() => ({ error: { message: 'nope' } })));
            component.onConfirm();

            expect(toast.error).toHaveBeenCalledWith('nope');
            expect(activeModal.close).not.toHaveBeenCalled();
        });
    });
});
