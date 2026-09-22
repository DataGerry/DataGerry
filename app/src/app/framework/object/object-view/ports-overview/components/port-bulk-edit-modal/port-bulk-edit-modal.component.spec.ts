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

import { ExtendableOptionCatalogService } from 'src/app/core/services/extendable-option-catalog.service';
import { LoaderService } from 'src/app/core/services/loader.service';
import { ToastService } from 'src/app/layout/toast/toast.service';

import { PortBulkUpdateRequest } from '../../models/port-bulk.types';
import { PortSelection } from '../../models/ports-overview.types';
import { PortService } from '../../services/port.service';
import { PortBulkEditModalComponent } from './port-bulk-edit-modal.component';
/* ------------------------------------------------------------------------------------------------------------------ */

describe('PortBulkEditModalComponent', () => {
    let component: PortBulkEditModalComponent;
    let portService: jasmine.SpyObj<PortService>;
    let toast: jasmine.SpyObj<ToastService>;
    let activeModal: jasmine.SpyObj<NgbActiveModal>;

    const ports: PortSelection[] = [
        { publicId: 9710, name: '1' },
        { publicId: 9711, name: '2' }
    ];

    const sentRequest = (): PortBulkUpdateRequest => portService.bulkUpdatePorts.calls.mostRecent().args[1];

    beforeEach(() => {
        portService = jasmine.createSpyObj<PortService>('PortService', ['bulkUpdatePorts']);
        toast = jasmine.createSpyObj<ToastService>('ToastService', ['success', 'error']);
        activeModal = jasmine.createSpyObj<NgbActiveModal>('NgbActiveModal', ['close', 'dismiss']);

        const catalog = jasmine.createSpyObj<ExtendableOptionCatalogService>('Catalog', ['optionsForTypes']);
        const loader = jasmine.createSpyObj<LoaderService>('LoaderService', ['show', 'hide'], { isLoading$: of(false) });

        catalog.optionsForTypes.and.returnValue(of(new Map()));
        portService.bulkUpdatePorts.and.returnValue(of(undefined));

        TestBed.configureTestingModule({
            providers: [
                { provide: PortService, useValue: portService },
                { provide: ExtendableOptionCatalogService, useValue: catalog },
                { provide: LoaderService, useValue: loader },
                { provide: ToastService, useValue: toast },
                { provide: NgbActiveModal, useValue: activeModal }
            ]
        }).overrideComponent(PortBulkEditModalComponent, { set: { template: '' } });

        component = TestBed.createComponent(PortBulkEditModalComponent).componentInstance;
        component.objectId = 20;
        component.ports = ports;
        component.ngOnInit();
    });

    it('writes nothing while no field is switched on', () => {
        component.onSubmit();

        expect(component.hasChanges).toBeFalse();
        expect(portService.bulkUpdatePorts).not.toHaveBeenCalled();
    });

    it('sends only the switched-on fields, so the rest stays untouched', () => {
        component.onToggleField('status', true);
        component.form.controls.status.setValue('9741');
        component.onSubmit();

        expect(sentRequest()).toEqual({ port_ids: [9710, 9711], values: { status: 9741 } });
    });

    it('sends a switched-on but empty field as null, which clears it on every port', () => {
        component.onToggleField('portType', true);
        component.onToggleField('description', true);
        component.form.controls.description.setValue('   ');
        component.onSubmit();

        expect(sentRequest().values).toEqual({ port_type: null, description: null });
    });

    it('trims a description before it is written', () => {
        component.onToggleField('description', true);
        component.form.controls.description.setValue('  Uplink to core  ');
        component.onSubmit();

        expect(sentRequest().values).toEqual({ description: 'Uplink to core' });
    });

    it('keeps the value while a field is switched off, and leaves it out of the request', () => {
        component.onToggleField('speed', true);
        component.form.controls.speed.setValue('9740');
        component.onToggleField('speed', false);
        component.onToggleField('status', true);
        component.onSubmit();

        expect(component.form.controls.speed.value).toBe('9740');
        expect(sentRequest().values).toEqual({ status: null });
    });

    it('refuses a description that is too long instead of sending it', () => {
        component.onToggleField('description', true);
        component.form.controls.description.setValue('x'.repeat(256));
        component.onSubmit();

        expect(portService.bulkUpdatePorts).not.toHaveBeenCalled();
        expect(component.descriptionError).toBe('This description is too long.');
    });

    it('closes once the write went through', () => {
        component.onToggleField('status', true);
        component.onSubmit();

        expect(toast.success).toHaveBeenCalled();
        expect(activeModal.close).toHaveBeenCalledWith(true);
    });

    it('stays open and reports when the write fails', () => {
        portService.bulkUpdatePorts.and.returnValue(throwError(() => ({ error: { message: 'nope' } })));

        component.onToggleField('status', true);
        component.onSubmit();

        expect(toast.error).toHaveBeenCalledWith('nope');
        expect(activeModal.close).not.toHaveBeenCalled();
    });
});
