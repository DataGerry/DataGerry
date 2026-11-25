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
import { DestroyRef, Injectable, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { HttpErrorResponse } from '@angular/common/http';
import { Observable, finalize, tap } from 'rxjs';

import { LoaderService } from 'src/app/core/services/loader.service';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { PermissionService } from 'src/app/modules/auth/services/permission.service';
import { PersonSyncService } from '../../services/person-sync.service';
import {
    GroupMapping,
    GroupMappingRequest,
    GroupSyncSettings,
    PERSON_SYNC_EDIT_RIGHT,
    SyncPassCounts
} from '../../models/person-sync';
/* ------------------------------------------------------------------------------------------------------------------ */

/** The user group mappings shared by the groups list's mapping cells and its summary. Provided per page. */
@Injectable()
export class GroupSyncStore {

    private readonly personSyncService = inject(PersonSyncService);
    private readonly permissionService = inject(PermissionService);
    private readonly loaderService = inject(LoaderService);
    private readonly toastService = inject(ToastService);
    private readonly destroyRef = inject(DestroyRef);

    /** The sync routes need this right; without it the page shows no sync state at all. */
    public readonly canEdit = this.permissionService.hasRight(PERSON_SYNC_EDIT_RIGHT)
        || this.permissionService.hasExtendedRight(PERSON_SYNC_EDIT_RIGHT);

    public readonly groupSync = signal<GroupSyncSettings | null>(null);
    public readonly lastPass = signal<SyncPassCounts | null>(null);
    public readonly isBusy = signal(false);

    public readonly mappingsByUserGroup = computed(() =>
        new Map((this.groupSync()?.mappings ?? []).map(mapping => [mapping.user_group_id, mapping]))
    );

/* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    public load(): void {
        if (!this.canEdit) {
            return;
        }

        this.run(this.personSyncService.getGroupSync().pipe(tap(groups => this.groupSync.set(groups))));
    }


    public map(userGroupId: number, request: GroupMappingRequest, groupName: string): void {
        this.run(this.personSyncService.mapUserGroup(userGroupId, request).pipe(tap(answer => {
            this.replaceMapping(userGroupId, answer.result);
            this.lastPass.set({ left: answer.left });
            this.toastService.success(`User group ${ groupName } was mapped!`);
        })));
    }


    public unmap(userGroupId: number, groupName: string): void {
        this.run(this.personSyncService.unmapUserGroup(userGroupId).pipe(tap(() => {
            this.replaceMapping(userGroupId, null);
            this.toastService.success(`User group ${ groupName } was unmapped!`);
        })));
    }

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    /** Runs one request behind the loader; a refusal is shown as the backend words it. */
    private run<T>(request$: Observable<T>): void {
        this.isBusy.set(true);
        this.loaderService.show();

        request$
            .pipe(
                takeUntilDestroyed(this.destroyRef),
                finalize(() => {
                    this.isBusy.set(false);
                    this.loaderService.hide();
                })
            )
            .subscribe({
                error: (error: HttpErrorResponse) => this.toastService.error(error?.error?.message)
            });
    }


    private replaceMapping(userGroupId: number, mapping: GroupMapping | null): void {
        const current = this.groupSync();

        if (!current) {
            return;
        }

        const mappings = current.mappings.filter(entry => entry.user_group_id !== userGroupId);

        this.groupSync.set({ ...current, mappings: mapping ? [...mappings, mapping] : mappings });
    }
}
