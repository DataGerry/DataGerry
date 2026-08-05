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
import { AuthProvider } from './providers';

const defaultAuthSettings = {
    _id: 'auth',
    enable_external: false,
    token_lifetime: 1500
};


export class AuthSettings {
    public readonly _id: string = defaultAuthSettings._id;
    public enable_external: boolean = defaultAuthSettings.enable_external;
    public token_lifetime: number = defaultAuthSettings.token_lifetime;
    public providers: Array<AuthProvider> = [];
}