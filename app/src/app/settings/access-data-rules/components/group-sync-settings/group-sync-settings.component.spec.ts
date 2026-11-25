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
import { PersonSyncService } from 'src/app/management/services/person-sync.service';
import { GroupSyncSettingsComponent } from './group-sync-settings.component';
/* ------------------------------------------------------------------------------------------------------------------ */

describe('GroupSyncSettingsComponent', () => {

    let fixture: ComponentFixture<GroupSyncSettingsComponent>;
    let personSync: jasmine.SpyObj<PersonSyncService>;
    let toast: jasmine.SpyObj<ToastService>;

    /** The protected form is read the way the template reads it. */
    const activeControl = () => (fixture.componentInstance as any).form.controls.active;

    function setUserSync(active: boolean | null): void {
        fixture.componentRef.setInput('userSyncActive', active);
        fixture.detectChanges();
    }

    beforeEach(() => {
        personSync = jasmine.createSpyObj<PersonSyncService>('PersonSyncService', ['getGroupSync', 'updateGroupSync']);
        toast = jasmine.createSpyObj<ToastService>('ToastService', ['success', 'error']);
        personSync.getGroupSync.and.returnValue(of({ active: true, mappings: [{ user_group_id: 10, person_group_id: 3 }] }));

        TestBed.configureTestingModule({
            imports: [GroupSyncSettingsComponent],
            providers: [
                { provide: PersonSyncService, useValue: personSync },
                { provide: ToastService, useValue: toast },
                { provide: LoaderService, useValue: jasmine.createSpyObj('LoaderService', ['show', 'hide']) }
            ]
        }).overrideComponent(GroupSyncSettingsComponent, { set: { template: '', imports: [] } });

        fixture = TestBed.createComponent(GroupSyncSettingsComponent);
    });


    it('waits for the person sync state before reading anything', () => {
        setUserSync(null);

        expect(personSync.getGroupSync).not.toHaveBeenCalled();
        expect(activeControl().disabled).toBeTrue();
    });


    it('reads the group sync once and enables the switch while the person sync is on', () => {
        setUserSync(true);

        expect(personSync.getGroupSync).toHaveBeenCalledTimes(1);
        expect(activeControl().value).toBeTrue();
        expect(activeControl().enabled).toBeTrue();
    });


    it('mirrors the server switching the group sync off, without a second read', () => {
        setUserSync(true);

        setUserSync(false);

        expect(personSync.getGroupSync).toHaveBeenCalledTimes(1);
        expect(activeControl().value).toBeFalse();
        expect(activeControl().disabled).toBeTrue();
    });


    it('stores a switch change and reports the pass', () => {
        const passes: unknown[] = [];
        const result = { active: false, mappings: [] };
        personSync.updateGroupSync.and.returnValue(of({ created: 0, edited: 1, left: [], result }));
        fixture.componentInstance.passCompleted.subscribe(value => passes.push(value));
        setUserSync(true);

        activeControl().setValue(false);
        fixture.detectChanges();

        expect(personSync.updateGroupSync).toHaveBeenCalledWith(false);
        expect(passes.length).toBe(1);
        expect(activeControl().value).toBeFalse();
    });


    it('falls back to the stored state after a refusal', () => {
        personSync.updateGroupSync.and.returnValue(throwError(() => ({
            status: 400,
            error: { message: 'The user group sync needs a Type carrying the PERSON_GROUP marker!' }
        })));
        setUserSync(true);

        activeControl().setValue(false);
        fixture.detectChanges();

        expect(toast.error).toHaveBeenCalledWith('The user group sync needs a Type carrying the PERSON_GROUP marker!');
        expect(activeControl().value).toBeTrue();
    });
});
