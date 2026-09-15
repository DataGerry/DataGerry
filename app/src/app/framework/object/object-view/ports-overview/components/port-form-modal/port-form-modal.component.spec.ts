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
import { CmdbPort, PortPayload, PortSide } from '../../models/ports-overview.types';
import { PortService } from '../../services/port.service';
import { PortFormModalComponent } from './port-form-modal.component';
/* ------------------------------------------------------------------------------------------------------------------ */

describe('PortFormModalComponent', () => {
    let component: PortFormModalComponent;
    let portService: jasmine.SpyObj<PortService>;
    let catalog: jasmine.SpyObj<ExtendableOptionCatalogService>;
    let loader: jasmine.SpyObj<LoaderService>;
    let toast: jasmine.SpyObj<ToastService>;
    let activeModal: jasmine.SpyObj<NgbActiveModal>;

    const storedPort: CmdbPort = {
        public_id: 7,
        object_id: 20,
        side: PortSide.SINGLE,
        name: 'Gi0/1',
        port_number: 3,
        status: 8803,
        port_type: 8805,
        speed: null,
        description: 'Uplink',
        author_id: 1,
        creation_time: null,
        last_edit_time: null
    };

    const sentPayload = (): PortPayload => portService.createPort.calls.mostRecent().args[0];

    beforeEach(() => {
        portService = jasmine.createSpyObj<PortService>('PortService', ['createPort', 'updatePort']);
        catalog = jasmine.createSpyObj<ExtendableOptionCatalogService>('Catalog', ['optionsForTypes']);
        loader = jasmine.createSpyObj<LoaderService>('LoaderService', ['show', 'hide'], { isLoading$: of(false) });
        toast = jasmine.createSpyObj<ToastService>('ToastService', ['success', 'error']);
        activeModal = jasmine.createSpyObj<NgbActiveModal>('NgbActiveModal', ['close', 'dismiss']);

        catalog.optionsForTypes.and.returnValue(of(new Map()));
        portService.createPort.and.returnValue(of(storedPort));
        portService.updatePort.and.returnValue(of(storedPort));

        TestBed.configureTestingModule({
            providers: [
                { provide: PortService, useValue: portService },
                { provide: ExtendableOptionCatalogService, useValue: catalog },
                { provide: LoaderService, useValue: loader },
                { provide: ToastService, useValue: toast },
                { provide: NgbActiveModal, useValue: activeModal }
            ]
        }).overrideComponent(PortFormModalComponent, { set: { template: '' } });

        component = TestBed.createComponent(PortFormModalComponent).componentInstance;
        component.objectId = 20;
    });

    describe('create', () => {
        beforeEach(() => component.ngOnInit());

        it('refuses a name of nothing but spaces', () => {
            component.form.patchValue({ name: '   ' });
            component.onSubmit();

            expect(portService.createPort).not.toHaveBeenCalled();
            expect(component.errorOf('name')).toBe('A port needs a name.');
        });

        it('sends an untouched select and an empty number as null, never as an empty string', () => {
            component.form.patchValue({ name: '  Gi0/1  ' });
            component.onSubmit();

            expect(sentPayload()).toEqual({
                object_id: 20,
                name: 'Gi0/1',
                port_number: null,
                status: null,
                port_type: null,
                speed: null,
                description: null
            });
        });

        it('sends the picked option ids as numbers', () => {
            component.form.patchValue({
                name: 'Gi0/1',
                portNumber: '3',
                status: '8803',
                portType: '8805',
                speed: '8804',
                description: 'Uplink'
            });
            component.onSubmit();

            expect(sentPayload()).toEqual({
                object_id: 20,
                name: 'Gi0/1',
                port_number: 3,
                status: 8803,
                port_type: 8805,
                speed: 8804,
                description: 'Uplink'
            });
        });

        it('reports the new port to its opener', () => {
            component.form.patchValue({ name: 'Gi0/1' });
            component.onSubmit();

            expect(toast.success).toHaveBeenCalled();
            expect(activeModal.close).toHaveBeenCalledWith(true);
        });

        it('keeps the form open when the backend refuses the write', () => {
            portService.createPort.and.returnValue(throwError(() => ({ error: { message: 'Name taken' } })));

            component.form.patchValue({ name: 'Gi0/1' });
            component.onSubmit();

            expect(toast.error).toHaveBeenCalledWith('Name taken');
            expect(activeModal.close).not.toHaveBeenCalled();
        });
    });

    describe('edit', () => {
        beforeEach(() => {
            component.port = storedPort;
            component.ngOnInit();
        });

        it('prefills from the stored port, option ids as select values', () => {
            expect(component.form.value).toEqual({
                name: 'Gi0/1',
                portNumber: '3',
                status: '8803',
                portType: '8805',
                speed: null,
                description: 'Uplink'
            });
        });

        it('updates the addressed port instead of creating a second one', () => {
            component.form.patchValue({ name: 'Gi0/2' });
            component.onSubmit();

            expect(portService.createPort).not.toHaveBeenCalled();
            expect(portService.updatePort).toHaveBeenCalledTimes(1);
            expect(portService.updatePort.calls.mostRecent().args[0]).toBe(7);
            expect(portService.updatePort.calls.mostRecent().args[1].name).toBe('Gi0/2');
        });

        it('titles itself as an edit', () => {
            expect(component.isEdit).toBeTrue();
            expect(component.title).toBe('Edit port');
            expect(component.submitLabel).toBe('Save changes');
        });
    });
});
