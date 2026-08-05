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

export enum AccessControlPermission {
    CREATE = 'CREATE',
    READ = 'READ',
    UPDATE = 'UPDATE',
    DELETE = 'DELETE'
}


export interface AccessControlListEntry<T> {
    [key: number]: Array<AccessControlPermission>;
}


export class AccessControlListSection<T> {
    public includes: AccessControlListEntry<T> = {};
}


export class AccessControlList {
    activated: boolean;
    groups?: AccessControlListSection<number>;

    constructor(activated: boolean, groups?: AccessControlListSection<number>) {
        this.activated = activated;
        this.groups = groups;
    }
}