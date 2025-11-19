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
import { Injectable } from '@angular/core';
import { ActivatedRouteSnapshot, RouterStateSnapshot } from '@angular/router';

import { Observable, map, catchError } from 'rxjs';

import { UserSetting } from '../models/user-setting';
import { UserSettingsDBService } from '../services/user-settings-db.service';
/* ------------------------------------------------------------------------------------------------------------------ */

/**
 * Resolver for the current user settings of a URL.
 */
@Injectable({
  providedIn: 'root'
})
export class UserSettingsResolver  {

    constructor(private userSettingsDB: UserSettingsDBService<UserSetting>) {

    }


    /**
     * Resolves data from the indexedDB by the current state URL.
     */
    public resolve(route: ActivatedRouteSnapshot, state: RouterStateSnapshot):
        Observable<UserSetting | unknown> | Promise<UserSetting | unknown> | UserSetting | unknown {
            const ident = state.url.toString().substring(1).split('/').join('-');

            return this.userSettingsDB.getSetting(ident).pipe(
                map((setting: UserSetting) => {
                    return setting;
                }),
                catchError((error) => {
                    return undefined;
                })
            );
    }
}