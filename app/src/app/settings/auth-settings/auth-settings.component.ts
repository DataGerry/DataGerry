/*
* DATAGERRY - OpenSource Enterprise CMDB
* Copyright (C) 2025 becon GmbH
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
import { Component, OnDestroy, OnInit } from '@angular/core';
import { UntypedFormArray, UntypedFormControl, UntypedFormGroup } from '@angular/forms';
import { ActivatedRoute, Data } from '@angular/router';

import { ReplaySubject, takeUntil } from 'rxjs';

import { ToastService } from '../../layout/toast/toast.service';
import { AuthService } from '../../modules/auth/services/auth.service';
import { GroupService } from '../../management/services/group.service';

import { AuthProvider } from '../../modules/auth/models/providers';
import { AuthSettings } from '../../modules/auth/models/settings';
import { Group } from '../../management/models/group';
import { APIGetMultiResponse } from '../../services/models/api-response';
import { CollectionParameters } from '../../services/models/api-parameter';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'cmdb-auth-settings',
    templateUrl: './auth-settings.component.html',
    styleUrls: ['./auth-settings.component.scss'],
    standalone: false
})
export class AuthSettingsComponent implements OnInit, OnDestroy {

    private subscriber: ReplaySubject<void> = new ReplaySubject<void>();

    public authConfigForm: UntypedFormGroup;
    public authSettings: AuthSettings;
    public installedProviderList: Array<AuthProvider>;

    public groups: Array<Group> = [];

/* -------------------------------------------------- GETTER/SETTER ------------------------------------------------- */

    public get providersArray(): UntypedFormArray {
        return this.authConfigForm.get('providers') as UntypedFormArray;
    }

/* ------------------------------------------------------------------------------------------------------------------ */
/*                                                     LIFE CYCLE                                                     */
/* ------------------------------------------------------------------------------------------------------------------ */

    public constructor(
        private authSettingsService: AuthService,
        private activateRoute: ActivatedRoute,
        private groupService: GroupService,
        private toast: ToastService
    ) {
        this.authConfigForm = new UntypedFormGroup({
            _id: new UntypedFormControl('auth'),
            enable_external: new UntypedFormControl(false),
            token_lifetime: new UntypedFormControl(null),
            providers: new UntypedFormArray([])
        });

        this.activateRoute.data.pipe(takeUntil(this.subscriber)).subscribe((data: Data) => {
            this.installedProviderList = data.providers;
        });
    }


    public ngOnInit(): void {
        this.authSettingsService.getSettings().pipe(takeUntil(this.subscriber)).subscribe((settings: any) => {
            this.authSettings = settings;
            this.authConfigForm.patchValue(this.authSettings);
        });

        const groupAPIParameters: CollectionParameters = {
            filter: undefined,
            limit: 0,
            sort: 'public_id',
            order: 1,
            page: 1
        };

        this.groupService.getGroups(groupAPIParameters).pipe(takeUntil(this.subscriber))
        .subscribe({
            next: (apiResponse: APIGetMultiResponse<Group>) => {
                this.groups = apiResponse.results as Array<Group>;
            },
            error: (error) => this.toast.error(error)
        });
    }


    public ngOnDestroy(): void {
        this.subscriber?.next();
        this.subscriber?.complete();
    }

/* ------------------------------------------------ HELPER FUNCTIONS ------------------------------------------------ */

    public onSave(): void {
        if (this.authConfigForm.valid) {
            this.authSettingsService.postSettings(this.authConfigForm.getRawValue()).pipe(
                takeUntil(this.subscriber)).subscribe(() => {
                    this.toast.success('Authentication config was updated!');
            });
        }
    }
}