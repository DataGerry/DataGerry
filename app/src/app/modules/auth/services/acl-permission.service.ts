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
* along with this program.  If not, see <https://www.gnu.org/licenses/>.
*/
import { Injectable } from '@angular/core';

import { AuthService } from './auth.service';

import { AccessControlList } from 'src/app/modules/acl/acl.types';
/* ------------------------------------------------------------------------------------------------------------------ */

@Injectable({
  providedIn: 'root'
})
export class AclPermissionService {

  private acl: AccessControlList;


/* --------------------------------------------------- LIFE CYLCE --------------------------------------------------- */

    constructor(private authService: AuthService) {

    }

/* ------------------------------------------------- HELPER METHODS ------------------------------------------------- */

    public checkRights(acl: AccessControlList, rights: string | string[]) {
        if (!acl.activated) {
            return null;
        }

        this.acl = acl;

        if (Array.isArray(rights)) {
            if (rights.length === 1) {
                return this.hasRight(rights[0]);
            }

            for (const right of rights) {
                if (!this.hasRight(right)) {
                    return false;
                }
            }
        } else {
            return this.hasRight(rights);
        }

        return true;
    }


    private hasRight(right: string) {
        const currentGroup = this.authService.currentUserValue.group_id;
        const rights = this.acl.groups.includes[currentGroup] as string[];

        if (!rights) {
            return false;
        }

        return rights.includes(right);
    }
}