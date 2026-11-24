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
import { ChangeDetectionStrategy, Component, inject, input } from '@angular/core';
import { RouterLink } from '@angular/router';

import { PermissionService } from 'src/app/modules/auth/services/permission.service';
import { PERSON_SYNC_EDIT_RIGHT } from '../../../models/person-sync';
/* ------------------------------------------------------------------------------------------------------------------ */

/** Marks a user whose last sync failed, with a way to Run sync for those who may run it. */
@Component({
    selector: 'app-user-sync-pending',
    standalone: true,
    imports: [RouterLink],
    changeDetection: ChangeDetectionStrategy.OnPush,
    templateUrl: './user-sync-pending.component.html',
    styleUrls: ['./user-sync-pending.component.scss']
})
export class UserSyncPendingComponent {

    private readonly permissionService = inject(PermissionService);

    public readonly pending = input(false);

    protected readonly canResync = this.permissionService.hasRight(PERSON_SYNC_EDIT_RIGHT)
        || this.permissionService.hasExtendedRight(PERSON_SYNC_EDIT_RIGHT);
}
