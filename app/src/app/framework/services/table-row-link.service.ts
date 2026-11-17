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

* You should have received a copy of the GNU Affero General Public License
* along with this program. If not, see <https://www.gnu.org/licenses/>.
*/
import { inject, Injectable } from '@angular/core';

import { PermissionService } from '../../modules/auth/services/permission.service';
import { AclPermissionService } from '../../modules/auth/services/acl-permission.service';

import { RenderResult } from '../models/cmdb-render';
import { AccessControlList } from '../../modules/acl/acl.types';
/* ------------------------------------------------------------------------------------------------------------------ */

/** Row click targets for the shared table; null when the user may not open the row. */
@Injectable({
    providedIn: 'root'
})
export class TableRowLinkService {

    private readonly permissionService = inject(PermissionService);
    private readonly aclPermissionService = inject(AclPermissionService);

/* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    public readonly objectView = (object: Partial<RenderResult>): string[] | null => {
        const publicID = object?.object_information?.object_id;

        if (!publicID || !this.isAllowed(['base.framework.object.view'], object.type_information?.acl, 'READ')) {
            return null;
        }

        return ['/', 'framework', 'object', 'view', String(publicID)];
    };


    public readonly typeEdit = (type: { public_id?: number }): string[] | null => {
        if (!type?.public_id || !this.isAllowed(['base.framework.type.view', 'base.framework.type.edit'])) {
            return null;
        }

        return ['/', 'framework', 'type', 'edit', String(type.public_id)];
    };

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    /** Same check as the `permissionLink` directive used by the row action links. */
    private isAllowed(rightNames: string[], acl?: AccessControlList, requirement?: string): boolean {
        const hasRights = rightNames.every(right =>
            this.permissionService.hasRight(right) || this.permissionService.hasExtendedRight(right)
        );

        if (!hasRights || !acl || !requirement) {
            return hasRights;
        }

        return this.aclPermissionService.checkRights(acl, requirement) ?? true;
    }
}
