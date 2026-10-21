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

import { of } from 'rxjs';

import { ExtendableOptionCatalogService } from 'src/app/core/services/extendable-option-catalog.service';
import { LoaderService } from 'src/app/core/services/loader.service';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { PortDeviceKind } from '../../models/port-bulk.types';
import { PortService } from '../../services/port.service';
import { PortCreateWizardModalComponent } from './port-create-wizard-modal.component';
/* ------------------------------------------------------------------------------------------------------------------ */

describe('PortCreateWizardModalComponent', () => {
    let activeModal: jasmine.SpyObj<NgbActiveModal>;

    const create = (existingKind: PortDeviceKind | null): PortCreateWizardModalComponent => {
        const component = TestBed.createComponent(PortCreateWizardModalComponent).componentInstance;
        component.objectId = 20;
        component.existingKind = existingKind;
        component.ngOnInit();
        return component;
    };

    beforeEach(() => {
        activeModal = jasmine.createSpyObj<NgbActiveModal>('NgbActiveModal', ['close', 'dismiss']);
        const catalog = jasmine.createSpyObj<ExtendableOptionCatalogService>('Catalog', ['optionsForTypes']);
        catalog.optionsForTypes.and.returnValue(of(new Map()));

        TestBed.configureTestingModule({
            providers: [
                { provide: NgbActiveModal, useValue: activeModal },
                { provide: PortService, useValue: jasmine.createSpyObj('PortService', ['previewPortNames', 'bulkCreatePorts']) },
                { provide: ExtendableOptionCatalogService, useValue: catalog },
                { provide: LoaderService, useValue: jasmine.createSpyObj('LoaderService', ['show', 'hide'], { isLoading$: of(false) }) },
                { provide: ToastService, useValue: jasmine.createSpyObj('ToastService', ['success', 'error']) }
            ]
        }).overrideComponent(PortCreateWizardModalComponent, { set: { template: '' } });
    });

    it('asks for a device type before the first step can be left', () => {
        const component = create(null);

        expect(component.canLeaveCurrentStep).toBeFalse();

        component.onNext();

        expect(component.typeError).toBe('Choose a device type.');
    });

    it('offers both device types while the object has no ports', () => {
        const component = create(null);

        component.onSelectDeviceKind(PortDeviceKind.STANDARD);

        expect(component.deviceKinds.every((choice) => !choice.disabled)).toBeTrue();
        expect(component.canLeaveCurrentStep).toBeTrue();
    });

    it('does not let a standard device become a patch panel', () => {
        const component = create(PortDeviceKind.STANDARD);

        component.onSelectDeviceKind(PortDeviceKind.PATCH_PANEL);

        expect(component.form.controls.deviceKind.value).toBe(PortDeviceKind.STANDARD);
    });

    it('starts a patch panel on the patch panel type, the only choice left', () => {
        const component = create(PortDeviceKind.PATCH_PANEL);

        expect(component.form.controls.deviceKind.value).toBe(PortDeviceKind.PATCH_PANEL);
        expect(component.canLeaveCurrentStep).toBeTrue();
    });
});
