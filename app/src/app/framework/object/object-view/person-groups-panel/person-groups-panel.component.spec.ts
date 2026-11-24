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
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { of, throwError } from 'rxjs';

import { LoaderService } from 'src/app/core/services/loader.service';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { PermissionService } from 'src/app/modules/auth/services/permission.service';
import { RenderResult } from 'src/app/framework/models/cmdb-render';
import { PersonSelection } from 'src/app/framework/models/person-selector';
import { ObjectPersonGroupsService } from 'src/app/framework/services/object-person-groups.service';
import { SystemRef } from 'src/app/management/models/person-sync';
import { PersonGroupsPanelComponent } from './person-groups-panel.component';
/* ------------------------------------------------------------------------------------------------------------------ */

const MAPPED: PersonSelection = {
    object_id: 3, type_id: 9803, type_label: 'Person group', kind: 'PERSON_GROUP', label: 'Field Service',
    active: true, system_ref: { kind: 'user_group', id: 9811 }
};

const HAND_MADE: PersonSelection = {
    object_id: 9821, type_id: 9803, type_label: 'Person group', kind: 'PERSON_GROUP', label: 'None',
    active: false, system_ref: null
};

function person(systemRef?: SystemRef, groupSyncActive?: boolean): RenderResult {
    return {
        object_information: { object_id: 2, system_ref: systemRef, group_sync_active: groupSyncActive }
    } as unknown as RenderResult;
}


describe('PersonGroupsPanelComponent', () => {

    let fixture: ComponentFixture<PersonGroupsPanelComponent>;
    let service: jasmine.SpyObj<ObjectPersonGroupsService>;
    let toast: jasmine.SpyObj<ToastService>;

    /** Protected members are read the way the template reads them. */
    const panel = () => fixture.componentInstance as any;

    function render(result: RenderResult): void {
        fixture = TestBed.createComponent(PersonGroupsPanelComponent);
        fixture.componentRef.setInput('renderResult', result);
        fixture.componentInstance.ngOnInit();
    }

    beforeEach(() => {
        service = jasmine.createSpyObj<ObjectPersonGroupsService>(
            'ObjectPersonGroupsService', ['getPersonGroups', 'changePersonGroups']);
        toast = jasmine.createSpyObj<ToastService>('ToastService', ['success', 'error']);
        service.getPersonGroups.and.returnValue(of([MAPPED, HAND_MADE]));

        const permissions = jasmine.createSpyObj<PermissionService>('PermissionService', ['hasRight', 'hasExtendedRight']);
        permissions.hasRight.and.returnValue(true);

        TestBed.configureTestingModule({
            imports: [PersonGroupsPanelComponent],
            providers: [
                { provide: ObjectPersonGroupsService, useValue: service },
                { provide: PermissionService, useValue: permissions },
                { provide: ToastService, useValue: toast },
                { provide: LoaderService, useValue: jasmine.createSpyObj('LoaderService', ['show', 'hide']) }
            ]
        }).overrideComponent(PersonGroupsPanelComponent, { set: { template: '', imports: [] } });
    });


    it('lists the person\'s groups and hides them from the picker', () => {
        render(person());

        expect(service.getPersonGroups).toHaveBeenCalledWith(2);
        expect(panel().rows().map((row: { label: string }) => row.label)).toEqual(['Field Service', 'None']);
        expect(panel().memberIds()).toEqual([3, 9821]);
        expect(panel().rows()[1].inactive).toBeTrue();
    });


    it('marks a synced person\'s mapped group as managed while the group sync runs', () => {
        render(person({ kind: 'user', id: 11 }, true));

        expect(panel().rows()[0].managed).toBeTrue();
        expect(panel().rows()[1].managed).toBeFalse();
    });


    it('leaves the mapped groups of an unsynced person free', () => {
        render(person(undefined, undefined));

        expect(panel().rows().some((row: { managed: boolean }) => row.managed)).toBeFalse();
    });


    it('adds the picked group and shows the groups the backend answers', () => {
        service.changePersonGroups.and.returnValue(of({ results: [MAPPED], failed: [] }));
        render(person());
        panel().addControl.setValue(3);

        panel().onAdd();

        expect(service.changePersonGroups).toHaveBeenCalledWith(2, { add: [3] });
        expect(panel().groups()).toEqual([MAPPED]);
        expect(panel().addControl.value).toBeNull();
    });


    it('never removes a managed group', () => {
        render(person({ kind: 'user', id: 11 }, true));

        panel().onRemove(panel().rows()[0]);

        expect(service.changePersonGroups).not.toHaveBeenCalled();
    });


    it('removes a free group', () => {
        service.changePersonGroups.and.returnValue(of({ results: [MAPPED], failed: [] }));
        render(person({ kind: 'user', id: 11 }, true));

        panel().onRemove(panel().rows()[1]);

        expect(service.changePersonGroups).toHaveBeenCalledWith(2, { remove: [9821] });
    });


    it('shows no panel and no error when the object is no person', () => {
        service.getPersonGroups.and.returnValue(throwError(() => ({ status: 404, error: {} })));
        render(person());

        expect(panel().isAvailable()).toBeFalse();
        expect(toast.error).not.toHaveBeenCalled();
    });
});
