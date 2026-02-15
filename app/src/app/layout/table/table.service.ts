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
import { Injectable, OnDestroy } from '@angular/core';

import { Observable, ReplaySubject, map } from 'rxjs';

import { UserSettingsDBService } from '../../management/user-settings/services/user-settings-db.service';
import { UserService } from 'src/app/management/services/user.service';

import { TableState, TableStatePayload } from './table.types';
import { UserSetting } from '../../management/user-settings/models/user-setting';
import { convertResourceURL } from '../../management/user-settings/services/user-settings.service';
/* ------------------------------------------------------------------------------------------------------------------ */
@Injectable({
    providedIn: 'root'
})
export class TableService<C = TableState> implements OnDestroy {

  private subscriber: ReplaySubject<void> = new ReplaySubject<void>();

/* ------------------------------------------------------------------------------------------------------------------ */
/*                                                     LIFE CYCLE                                                     */
/* ------------------------------------------------------------------------------------------------------------------ */

    constructor(
        private indexDB: UserSettingsDBService<UserSetting, TableStatePayload>,
        private userService: UserService
    ) {

    }


    public ngOnDestroy(): void {
        this.subscriber?.next();
        this.subscriber?.complete();
    }

/* --------------------------------------------------- CRUD - READ -------------------------------------------------- */

    /**
     * Get the table state payload from a user setting
     * @param url
     * @param id
     */
    public getTableStatePayload(url: string, id: string): Observable<TableStatePayload> {
        return this.indexDB.getSetting(url).pipe(
            map((setting: UserSetting<TableStatePayload>) => {
                return setting.payloads.find(payload => payload.id === id);
            })
        );
    }


    /**
     * Get all states from a user setting.
     * @param url
     * @param id
     */
    public getTableStates(url: string, id: string): Observable<Array<TableState>> {
        return this.indexDB.getSetting(url).pipe(
            map((setting: UserSetting<TableStatePayload>) => {
                return setting.payloads.find(payload => payload.id === id).tableStates;
            })
        );
    }


    /**
     * Get a the current table state
     * @param url
     * @param id
     */
    public getTableState(url: string, id: string): Observable<TableState> {
        return this.indexDB.getSetting(url).pipe(
            map((setting: UserSetting<TableStatePayload>) => {
                return setting.payloads.find(payload => payload.id === id).currentState;
            })
        );
    }

/* -------------------------------------------------- CRUD - UPDATE ------------------------------------------------- */

    /**
     * Add a table state to a user setting.
     * @param url
     * @param id
     * @param state
     */
    public addTableState(url: string, id: string, state: TableState) {
        const resource: string = convertResourceURL(url);

        this.indexDB.getSetting(resource).subscribe((setting: UserSetting<TableStatePayload>) => {
            if (setting) {
                setting.payloads.find(payload => payload.id === id).tableStates.push(state);
                this.indexDB.updateSetting(setting);
            } else {
                let userTableStatePayload: TableStatePayload = {
                    "id": id,
                    "tableStates": [
                        state
                    ],
                    currentState: state
                }

                let userSetting = new UserSetting<TableStatePayload>(resource,
                                                                    this.userService.getCurrentUser().public_id,
                                                                    [userTableStatePayload]);
                this.indexDB.updateSetting(userSetting);
            }
        });
    }


    /**
     * Set the current table state
     * @param url
     * @param id
     * @param state
     */
    public setCurrentTableState(url: string, id: string, state: TableState) {
        const resource: string = convertResourceURL(url);

        this.indexDB.getSetting(resource).subscribe((setting: UserSetting<TableStatePayload>) => {
            const payload = setting?.payloads.find(payload => payload.id === id);

            if (payload) {
                payload.currentState = state;
                this.indexDB.updateSetting(setting);
            }
        });
    }


    public updateTableState(url: string, id: string, state: TableState, update: TableState) {
        const resource: string = convertResourceURL(url);

        this.indexDB.getSetting(resource).subscribe((setting: UserSetting<TableStatePayload>) => {
            const tableStates = setting.payloads.find(payload => payload.id === id).tableStates;
            const stateIDX = tableStates.findIndex(s => s.name === state.name);
            setting.payloads.find(payload => payload.id === id).tableStates[stateIDX] = update;
            this.indexDB.updateSetting(setting);
        });
    }

/* -------------------------------------------------- CRUD - DELETE ------------------------------------------------- */

    /**
     * Remove a table state from the payload.
     * @param url
     * @param id
     * @param state
     */
    public removeTableState(url: string, id: string, state: TableState) {
        const resource: string = convertResourceURL(url);

        this.indexDB.getSetting(resource).subscribe((setting: UserSetting<TableStatePayload>) => {
            const states = setting.payloads.find(payload => payload.id === id).tableStates;
            const stateIdx = states.findIndex(s => s.name === state.name);

            if (stateIdx > -1) {
                states.splice(stateIdx, 1);
                this.indexDB.updateSetting(setting);
            }
        });
    }
}
