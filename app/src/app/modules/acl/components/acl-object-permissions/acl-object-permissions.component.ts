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
import { Component, Input, OnChanges, SimpleChanges } from '@angular/core';

import { AccessControlList, AccessControlPermission } from '../../acl.types';
import { Group } from 'src/app/management/models/group';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'cmdb-acl-object-permissions',
    templateUrl: './acl-object-permissions.component.html',
    styleUrls: ['./acl-object-permissions.component.scss'],
    standalone: false
})
export class AclObjectPermissionsComponent implements OnChanges {
    // Selected group which compares to the acl
    @Input() public group: Group;

    // ACL of the current row type
    @Input() public acl: AccessControlList;

    public permissions: Array<AccessControlPermission> = [];

/* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    public ngOnChanges(changes: SimpleChanges): void {
        this.generate();
    }

/* ------------------------------------------------ HELPER FUNCTIONS ------------------------------------------------ */

    /**
     * Generates the permissions for the object if there are any
     */
    public generate(): void {
        if (!this.group || !this.acl) {
            this.permissions = [];
        } else {
            const groupID: number = this.group.public_id;

            if (groupID in this.acl.groups.includes) {
                this.permissions = this.acl.groups.includes[groupID];
            }
        }
    }
}