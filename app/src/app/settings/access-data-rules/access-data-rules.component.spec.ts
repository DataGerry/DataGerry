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
import { EMPTY, of, throwError } from 'rxjs';

import { LoaderService } from 'src/app/core/services/loader.service';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { TypeService } from 'src/app/framework/services/type.service';
import { PermissionService } from 'src/app/modules/auth/services/permission.service';
import { UserService } from 'src/app/management/services/user.service';
import { PersonSyncService } from 'src/app/management/services/person-sync.service';
import { PersonSyncDialogService } from 'src/app/management/person-sync/person-sync-dialog.service';
import { UserSyncSettings } from 'src/app/management/models/person-sync';
import { AccessDataRulesComponent } from './access-data-rules.component';
/* ------------------------------------------------------------------------------------------------------------------ */

const STORED_ON: UserSyncSettings = { active: true, default_type_id: 9801, type_overrides: [] };
const STORED_OFF: UserSyncSettings = { active: false, default_type_id: null, type_overrides: [] };

const PERSON_TYPES = {
    results: [
        { public_id: 9801, name: 'person', label: 'Person', active: true },
        { public_id: 9802, name: 'external', label: 'External', active: false }
    ]
};

const USERS = { results: [{ public_id: 1, user_name: 'admin' }, { public_id: 9813, user_name: 'anna' }] };


describe('AccessDataRulesComponent', () => {

    let personSync: jasmine.SpyObj<PersonSyncService>;
    let dialogs: jasmine.SpyObj<PersonSyncDialogService>;
    let toast: jasmine.SpyObj<ToastService>;
    let types: jasmine.SpyObj<TypeService>;

    function create(stored: UserSyncSettings, typeList = PERSON_TYPES): AccessDataRulesComponent {
        personSync.getUserSync.and.returnValue(of(stored));
        types.getTypes.and.returnValue(of(typeList) as any);

        const fixture = TestBed.createComponent(AccessDataRulesComponent);
        fixture.componentInstance.ngOnInit();

        return fixture.componentInstance;
    }

    function pass(result: UserSyncSettings) {
        return of({ created: 1, edited: 0, moved: 0, copied: 0, left: [], result });
    }

    beforeEach(() => {
        personSync = jasmine.createSpyObj<PersonSyncService>(
            'PersonSyncService', ['getUserSync', 'updateUserSync', 'checkUserSync', 'resync']);
        dialogs = jasmine.createSpyObj<PersonSyncDialogService>('PersonSyncDialogService', ['confirm', 'confirmCopyBlocked']);
        toast = jasmine.createSpyObj<ToastService>('ToastService', ['success', 'error']);
        types = jasmine.createSpyObj<TypeService>('TypeService', ['getTypes']);

        const users = jasmine.createSpyObj<UserService>('UserService', ['getUsers']);
        users.getUsers.and.returnValue(of(USERS) as any);

        const permissions = jasmine.createSpyObj<PermissionService>('PermissionService', ['hasRight', 'hasExtendedRight']);
        permissions.hasRight.and.returnValue(true);

        TestBed.configureTestingModule({
            imports: [AccessDataRulesComponent],
            providers: [
                { provide: PersonSyncService, useValue: personSync },
                { provide: PersonSyncDialogService, useValue: dialogs },
                { provide: ToastService, useValue: toast },
                { provide: TypeService, useValue: types },
                { provide: UserService, useValue: users },
                { provide: PermissionService, useValue: permissions },
                { provide: LoaderService, useValue: jasmine.createSpyObj('LoaderService', ['show', 'hide'], { isLoading$: of(false) }) }
            ]
        }).overrideComponent(AccessDataRulesComponent, { set: { template: '', imports: [] } });
    });


    describe('loading', () => {
        it('fills the form from the stored settings and keeps it pristine', () => {
            const component = create({ ...STORED_ON, type_overrides: [{ user_id: 9813, type_id: 9802 }] });

            expect(component.form.getRawValue()).toEqual({
                active: true,
                default_type_id: 9801,
                type_overrides: [{ user_id: 9813, type_id: 9802 }]
            });
            expect(component.form.pristine).toBeTrue();
        });

        it('lists the PERSON Types and marks a deactivated one', () => {
            const component = create(STORED_OFF);

            expect(types.getTypes.calls.mostRecent().args[0].filter).toEqual({ special_type: 'PERSON' });
            expect(component.typeOptions()).toEqual([
                { public_id: 9801, label: 'Person' },
                { public_id: 9802, label: 'External (deactivated)' }
            ]);
        });

        it('locks the switch while no Type carries PERSON', () => {
            const component = create(STORED_OFF, { results: [] });

            expect(component.hasPersonTypes()).toBeFalse();
            expect(component.form.controls.active.disabled).toBeTrue();
        });

        it('keeps the switch usable without a PERSON Type while the sync is on, so it can be switched off', () => {
            const component = create(STORED_ON, { results: [] });

            expect(component.form.controls.active.enabled).toBeTrue();
        });
    });


    describe('saving', () => {
        it('saves directly when no target Type changed', () => {
            const component = create(STORED_ON);
            personSync.updateUserSync.and.returnValue(pass(STORED_ON));
            component.form.markAsDirty();

            component.onSave();

            expect(personSync.checkUserSync).not.toHaveBeenCalled();
            expect(personSync.updateUserSync).toHaveBeenCalledWith(STORED_ON);
            expect(component.lastPass()?.created).toBe(1);
            expect(component.form.pristine).toBeTrue();
        });

        it('does not save an override row without a user', () => {
            const component = create(STORED_ON);
            component.onAddOverride();

            component.onSave();

            expect(personSync.updateUserSync).not.toHaveBeenCalled();
        });

        it('asks before switching the sync off and saves only on confirm', () => {
            const component = create(STORED_ON);
            dialogs.confirm.and.returnValue(EMPTY);
            component.form.controls.active.setValue(false);

            component.onSave();

            expect(dialogs.confirm).toHaveBeenCalled();
            expect(personSync.updateUserSync).not.toHaveBeenCalled();

            dialogs.confirm.and.returnValue(of(undefined));
            personSync.updateUserSync.and.returnValue(pass({ ...STORED_ON, active: false }));

            component.onSave();

            expect(personSync.updateUserSync).toHaveBeenCalledWith({ ...STORED_ON, active: false });
        });

        it('checks a target change and saves at once when nobody moves', () => {
            const component = create(STORED_ON);
            personSync.checkUserSync.and.returnValue(of({ relocations: [], blocked: 0 }));
            personSync.updateUserSync.and.returnValue(pass({ ...STORED_ON, default_type_id: 9802 }));
            component.form.controls.default_type_id.setValue(9802);

            component.onSave();

            expect(personSync.checkUserSync).toHaveBeenCalledWith({ ...STORED_ON, default_type_id: 9802 });
            expect(dialogs.confirm).not.toHaveBeenCalled();
            expect(personSync.updateUserSync).toHaveBeenCalled();
        });

        it('confirms the move when persons move and none is blocked', () => {
            const component = create(STORED_ON);
            personSync.checkUserSync.and.returnValue(of({
                relocations: [{ user_id: 1, person_id: 1, from_type_id: 9801, to_type_id: 9802, blockers: [] }],
                blocked: 0
            }));
            dialogs.confirm.and.returnValue(of(undefined));
            personSync.updateUserSync.and.returnValue(pass(STORED_ON));
            component.form.controls.default_type_id.setValue(9802);

            component.onSave();

            expect(dialogs.confirm.calls.mostRecent().args[0].message).toBe('1 person(s) move to their new Type.');
            expect(personSync.updateUserSync.calls.mostRecent().args[0].on_blocked).toBeUndefined();
        });

        it('sends on_blocked copy after the blocked persons were confirmed', () => {
            const component = create(STORED_ON);
            personSync.checkUserSync.and.returnValue(of({
                relocations: [{ user_id: 1, person_id: 1, from_type_id: 9801, to_type_id: 9802, blockers: ['badge'] }],
                blocked: 1
            }));
            dialogs.confirmCopyBlocked.and.returnValue(of(undefined));
            personSync.updateUserSync.and.returnValue(pass(STORED_ON));
            component.form.controls.default_type_id.setValue(9802);

            component.onSave();

            expect(dialogs.confirmCopyBlocked.calls.mostRecent().args[0][0].user_label).toBe('admin');
            expect(personSync.updateUserSync.calls.mostRecent().args[0].on_blocked).toBe('copy');
        });

        it('changes nothing when the blocked persons dialog is cancelled', () => {
            const component = create(STORED_ON);
            personSync.checkUserSync.and.returnValue(of({
                relocations: [{ user_id: 1, person_id: 1, from_type_id: 9801, to_type_id: 9802, blockers: ['badge'] }],
                blocked: 1
            }));
            dialogs.confirmCopyBlocked.and.returnValue(EMPTY);
            component.form.controls.default_type_id.setValue(9802);

            component.onSave();

            expect(personSync.updateUserSync).not.toHaveBeenCalled();
        });

        it('offers a retry after a pass failed midway and sends the same settings again', () => {
            const component = create(STORED_ON);
            personSync.updateUserSync.and.returnValue(throwError(() => ({ status: 500, error: {} })));

            component.onSave();

            expect(component.retryAction()).not.toBeNull();
            expect(toast.error).not.toHaveBeenCalled();

            personSync.updateUserSync.and.returnValue(pass(STORED_ON));
            component.onRetry();

            expect(personSync.updateUserSync).toHaveBeenCalledTimes(2);
            expect(personSync.updateUserSync.calls.argsFor(1)).toEqual(personSync.updateUserSync.calls.argsFor(0));
            expect(component.retryAction()).toBeNull();
        });

        it('shows a refusal as the backend words it', () => {
            const component = create(STORED_OFF);
            personSync.updateUserSync.and.returnValue(throwError(() => ({
                status: 400,
                error: { message: 'The user sync needs a default person Type before it can be switched on!' }
            })));
            component.form.controls.active.setValue(true);

            component.onSave();

            expect(toast.error).toHaveBeenCalledWith('The user sync needs a default person Type before it can be switched on!');
            expect(component.retryAction()).toBeNull();
        });
    });


    describe('dry run and run sync', () => {
        it('lists the relocations of the form as it stands without saving', () => {
            const component = create(STORED_ON);
            personSync.checkUserSync.and.returnValue(of({
                relocations: [{ user_id: 9813, person_id: 2, from_type_id: 9801, to_type_id: 9802, blockers: [] }],
                blocked: 0
            }));
            component.form.controls.default_type_id.setValue(9802);

            component.onDryRun();

            expect(component.dryRunRows()?.[0].user_label).toBe('anna');
            expect(personSync.updateUserSync).not.toHaveBeenCalled();
        });

        it('keeps the form as it is after a resync, which answers only counts', () => {
            const component = create(STORED_ON);
            personSync.resync.and.returnValue(of({ created: 0, edited: 2, left: [] }));

            component.onRunSync();

            expect(component.form.getRawValue().default_type_id).toBe(9801);
            expect(component.stored()).toEqual(STORED_ON);
            expect(component.lastPass()).toEqual({ created: 0, edited: 2, left: [] });
        });
    });
});
