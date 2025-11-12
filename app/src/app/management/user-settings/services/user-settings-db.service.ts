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
import { Injectable, OnDestroy } from '@angular/core';

import { Observable, ReplaySubject, Subject, takeUntil } from 'rxjs';

import { UserSettingsService } from './user-settings.service';
import { NgxIndexedDBService } from 'ngx-indexed-db';

import { UserSetting, UserSettingPayload } from '../models/user-setting';
import { User } from '../../models/user';
/* ------------------------------------------------------------------------------------------------------------------ */
@Injectable({
    providedIn: 'root'
})
export class UserSettingsDBService<T = UserSetting, P = UserSettingPayload> implements OnDestroy {
    // Name of the store settings of the indexedDB `DATAGERRY`
    private readonly storeName: string = 'user-settings';

    // Subscriber subject. When active auto set to backend db
    private subscriber: ReplaySubject<void> = new ReplaySubject<void>();

    // Holder subject when new settings are in the database
    private newSettings: Subject<UserSetting> = new Subject<UserSetting>();

/* ------------------------------------------------------------------------------------------------------------------ */
/*                                                     LIFE CYCLE                                                     */
/* ------------------------------------------------------------------------------------------------------------------ */

    constructor(
        private dbService: NgxIndexedDBService,
        private userSettingsService: UserSettingsService<UserSetting<P>>
    ) {
        this.newSettings.asObservable().pipe(takeUntil(this.subscriber)).subscribe();

        this.userSettingsService.currentUserObservable.subscribe((user: User) => {
            if (user) {
                this.syncSettings().then(() => {
                // console.log('User settings loaded');
                });
            }
        });
    }


    /**
     * Auto unsubscribe when service is destroyed.
     */
    public ngOnDestroy(): void {
        this.subscriber?.next();
        this.subscriber?.complete();
    }

/* ------------------------------------------------- HELPER METHODS ------------------------------------------------- */

    /**
     * Add a setting to the database
     * @param setting UserSetting data
     */
    public addSetting(setting: UserSetting<P>): void {
        if (!this.dbService.getByKey(this.storeName, setting as any)) {
            this.dbService.add(this.storeName, setting).subscribe(key => {
                this.userSettingsService.addUserSetting(setting).pipe(takeUntil(this.subscriber))
                .subscribe();
            });
        }
    }


    /**
     * Get a setting by it ident
     * @param resource Identifier of the setting
     */
    public getSetting(resource: string): Observable<UserSetting<P>> {
        return this.dbService.getByKey(this.storeName, resource);
    }


    /**
     * Update a existing user setting
     * @param setting UserSetting data
     */
    public updateSetting(setting: UserSetting<P>): void {
        this.dbService.update(this.storeName, setting).subscribe(key => {
            this.userSettingsService.updateUserSetting(setting.resource, setting)
            .pipe(takeUntil(this.subscriber)).subscribe();
        });
    }


    /**
     * Delete a existing user setting.
     * @param id User key.
     */
    public deleteSetting(id: string): void {
        this.dbService.delete(this.storeName, id).subscribe(key => {
            this.userSettingsService.deleteUserSetting(id).pipe(takeUntil(this.subscriber)).subscribe();
        });
    }

    /**
     * Syncs the indexedDB settings with database.
     */
    public async syncSettings() {
        try {
            this.userSettingsService.getUserSettings()
                .subscribe({
                    next: async (userSettings: Array<UserSetting<P>>) => {
                        this.dbService.clear(this.storeName).subscribe(() => { });

                        for (const setting of userSettings) {
                            this.dbService.add(this.storeName, setting).subscribe();
                        }
                    },
                    error: (error) => console.error(`Error while loading user settings: ${error}`)
                });
        } catch (e) {
            // console.error(`Error while init user settings: ${e}`);
        }
    }    

    /**
     * Clear the settings database
     */
    public clear(): void {
        this.dbService.clear(this.storeName);
    }
}
