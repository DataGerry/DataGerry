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
import { TestBed, fakeAsync, tick } from '@angular/core/testing';
import { NgbModal } from '@ng-bootstrap/ng-bootstrap';

import { of, throwError } from 'rxjs';

import { ExtendableOptionManagerService } from './extendable-option-manager.service';
import { ExtendableOptionCatalogService } from './extendable-option-catalog.service';
import { LoaderService } from './loader.service';
import { ExtendableOptionService } from 'src/app/toolbox/isms/services/extendable-option.service';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { PortOptionType } from 'src/app/framework/models/port-option-type';

/**
 * The manager is the single entry point for extending a select's options, so what matters here is
 * that it only opens for a manageable type and that the catalog is refreshed however the modal ends.
 */
describe('ExtendableOptionManagerService', () => {
    let service: ExtendableOptionManagerService;
    let optionService: jasmine.SpyObj<ExtendableOptionService>;
    let catalog: jasmine.SpyObj<ExtendableOptionCatalogService>;
    let loader: jasmine.SpyObj<LoaderService>;
    let toast: jasmine.SpyObj<ToastService>;
    let modal: jasmine.SpyObj<NgbModal>;

    function stubModal(result: Promise<unknown>): { componentInstance: Record<string, unknown> } {
        const modalRef = { componentInstance: {} as Record<string, unknown>, result };
        modal.open.and.returnValue(modalRef as any);
        return modalRef;
    }

    beforeEach(() => {
        optionService = jasmine.createSpyObj<ExtendableOptionService>('ExtendableOptionService',
            ['getExtendableOptionsByType']);
        catalog = jasmine.createSpyObj<ExtendableOptionCatalogService>('ExtendableOptionCatalogService', ['invalidate']);
        loader = jasmine.createSpyObj<LoaderService>('LoaderService', ['show', 'hide']);
        toast = jasmine.createSpyObj<ToastService>('ToastService', ['error']);
        modal = jasmine.createSpyObj<NgbModal>('NgbModal', ['open']);

        TestBed.configureTestingModule({
            providers: [
                ExtendableOptionManagerService,
                { provide: ExtendableOptionService, useValue: optionService },
                { provide: ExtendableOptionCatalogService, useValue: catalog },
                { provide: LoaderService, useValue: loader },
                { provide: ToastService, useValue: toast },
                { provide: NgbModal, useValue: modal }
            ]
        });

        service = TestBed.inject(ExtendableOptionManagerService);
    });

    it('reports only the registered option types as manageable', () => {
        expect(service.isManageable(PortOptionType.STATUS)).toBeTrue();
        expect(service.isManageable('CONTROL_MEASURE')).toBeFalse();
        expect(service.isManageable(undefined)).toBeFalse();
    });

    it('does not request or open anything for an option type that is not manageable', () => {
        let emitted = false;
        service.open('CONTROL_MEASURE').subscribe(() => (emitted = true));

        expect(optionService.getExtendableOptionsByType).not.toHaveBeenCalled();
        expect(modal.open).not.toHaveBeenCalled();
        expect(emitted).toBeFalse();
    });

    it('hands the current options to the manager and refreshes the catalog once it closes', fakeAsync(() => {
        const options = [{ public_id: 3, value: 'Up', option_type: PortOptionType.STATUS, predefined: true }];
        optionService.getExtendableOptionsByType.and.returnValue(of({ results: options } as any));
        const modalRef = stubModal(Promise.resolve());

        let emitted = false;
        service.open(PortOptionType.STATUS).subscribe(() => (emitted = true));
        tick();

        expect(optionService.getExtendableOptionsByType).toHaveBeenCalledWith(PortOptionType.STATUS);
        expect(modalRef.componentInstance.options).toBe(options);
        expect(modalRef.componentInstance.optionType).toBe(PortOptionType.STATUS);
        expect(modalRef.componentInstance.itemLabel).toBe('Port Status');
        expect(catalog.invalidate).toHaveBeenCalledWith(PortOptionType.STATUS);
        expect(emitted).toBeTrue();
    }));

    it('refreshes the catalog even when the manager is dismissed', fakeAsync(() => {
        optionService.getExtendableOptionsByType.and.returnValue(of({ results: [] } as any));
        stubModal(Promise.reject('dismissed'));

        let emitted = false;
        service.open(PortOptionType.SPEED).subscribe(() => (emitted = true));
        tick();

        expect(catalog.invalidate).toHaveBeenCalledWith(PortOptionType.SPEED);
        expect(emitted).toBeTrue();
    }));

    it('shows the loader per subscription, not when open() is called', () => {
        optionService.getExtendableOptionsByType.and.returnValue(of({ results: [] } as any));
        stubModal(Promise.resolve());

        const request = service.open(PortOptionType.PORT_TYPE);
        expect(loader.show).not.toHaveBeenCalled();

        request.subscribe();
        expect(loader.show).toHaveBeenCalledTimes(1);
        expect(loader.hide).toHaveBeenCalledTimes(1);
    });

    it('reports a failed load and opens nothing', () => {
        optionService.getExtendableOptionsByType.and.returnValue(
            throwError(() => ({ error: { message: 'no access' } }))
        );

        let emitted = false;
        service.open(PortOptionType.STATUS).subscribe(() => (emitted = true));

        expect(toast.error).toHaveBeenCalledWith('no access');
        expect(modal.open).not.toHaveBeenCalled();
        expect(catalog.invalidate).not.toHaveBeenCalled();
        expect(emitted).toBeFalse();
    });
});
