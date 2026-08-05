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
import { ObjectStoreSchema } from 'ngx-indexed-db';
/* ------------------------------------------------------------------------------------------------------------------ */

export const userSettingsSchema: ObjectStoreSchema[] = [
    { name: 'resource', keypath: 'resource', options: { unique: true } },
    { name: 'user_id', keypath: 'user_id', options: { unique: false } },
    { name: 'payloads', keypath: 'payloads', options: { unique: false } },
    { name: 'setting_type', keypath: 'setting_type', options: { unique: false } }
];

/**
 * Basic user setting class. Wrapper class for all CRUD functions with the API.
 */
export class UserSetting<P = UserSettingPayload> {
    static readonly USER_SETTING_TYPE = 'APPLICATION';

    public readonly resource: string;
    public readonly user_id: number;
    public payloads: Array<P>;
    public readonly setting_type: string = UserSetting.USER_SETTING_TYPE;


    constructor(resource: string, user_id: number, payloads: Array<P> = []) {
        this.resource = resource;
        this.user_id = user_id;
        this.payloads = payloads;
    }
}


export interface UserSettingPayload {
    id: string;
}
