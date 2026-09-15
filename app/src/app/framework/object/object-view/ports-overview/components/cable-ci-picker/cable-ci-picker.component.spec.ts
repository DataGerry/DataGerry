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
import { ComponentFixture, TestBed, fakeAsync, tick } from '@angular/core/testing';

import { of } from 'rxjs';

import { CoreModule } from 'src/app/core/core.module';
import { LoaderService } from 'src/app/core/services/loader.service';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { APIGetMultiResponse } from 'src/app/services/models/api-response';

import { UnassignedCable } from '../../models/port-connection.types';
import { PortConnectionService } from '../../services/port-connection.service';
import { CableCiPickerComponent } from './cable-ci-picker.component';
/* ------------------------------------------------------------------------------------------------------------------ */

const CABLES: UnassignedCable[] = [
    { public_id: 9933, name: 'alpha patch', cable_type: 'CAT6a', active: true },
    { public_id: 9935, name: 'retired patch', cable_type: 'CAT6', active: false }
];

function page(results: UnassignedCable[], total = results.length): APIGetMultiResponse<UnassignedCable> {
    return { results, count: results.length, total } as APIGetMultiResponse<UnassignedCable>;
}


describe('CableCiPickerComponent', () => {

    let fixture: ComponentFixture<CableCiPickerComponent>;
    let component: CableCiPickerComponent;
    let portConnectionService: jasmine.SpyObj<PortConnectionService>;

    beforeEach(async () => {
        portConnectionService = jasmine.createSpyObj<PortConnectionService>(
            'PortConnectionService', ['getUnassignedCables']);
        portConnectionService.getUnassignedCables.and.returnValue(of(page(CABLES)));

        await TestBed.configureTestingModule({
            imports: [CoreModule, CableCiPickerComponent],
            providers: [
                { provide: PortConnectionService, useValue: portConnectionService },
                { provide: LoaderService, useValue: jasmine.createSpyObj<LoaderService>('LoaderService', ['show', 'hide']) },
                { provide: ToastService, useValue: jasmine.createSpyObj<ToastService>('ToastService', ['error']) }
            ]
        }).compileComponents();

        fixture = TestBed.createComponent(CableCiPickerComponent);
        component = fixture.componentInstance;
    });

    it('opens on the first page of unassigned cables', () => {
        fixture.detectChanges();

        expect(portConnectionService.getUnassignedCables).toHaveBeenCalledWith(
            jasmine.objectContaining({ page: 1, search: undefined, connectionId: null }));
    });

    it('asks for the cable of the connection being edited, so it can be preselected', () => {
        fixture.componentRef.setInput('connectionId', 1);
        component.writeValue(9935);
        fixture.detectChanges();

        expect(portConnectionService.getUnassignedCables).toHaveBeenCalledWith(
            jasmine.objectContaining({ connectionId: 1 }));
    });

    it('names the preselected cable once its page has arrived', () => {
        const selected: UnassignedCable[] = [];
        component.cableSelected.subscribe((option) => selected.push(option as unknown as UnassignedCable));

        component.writeValue(9935);
        fixture.detectChanges();

        expect(selected.length).toBe(1);
        expect((selected[0] as unknown as { option_label: string }).option_label)
            .toBe('retired patch (CAT6, inactive)');
    });

    it('searches server side, starting the list over on the new term', fakeAsync(() => {
        fixture.detectChanges();
        portConnectionService.getUnassignedCables.calls.reset();

        component['searchTerms$'].next(' alpha ');
        tick(500);

        expect(portConnectionService.getUnassignedCables).toHaveBeenCalledWith(
            jasmine.objectContaining({ page: 1, search: 'alpha' }));
    }));
});
