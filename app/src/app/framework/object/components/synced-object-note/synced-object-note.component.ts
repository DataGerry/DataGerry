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
import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import { RouterLink } from '@angular/router';

import { PermissionService } from 'src/app/modules/auth/services/permission.service';
import { RenderResult } from '../../../models/cmdb-render';
import { SyncSourceLink } from 'src/app/management/models/person-sync';
/* ------------------------------------------------------------------------------------------------------------------ */

/** Names the user-management record a synced object mirrors. */
@Component({
    selector: 'cmdb-synced-object-note',
    standalone: true,
    imports: [RouterLink],
    changeDetection: ChangeDetectionStrategy.OnPush,
    templateUrl: './synced-object-note.component.html',
    styleUrls: ['./synced-object-note.component.scss']
})
export class SyncedObjectNoteComponent {

    private readonly permissionService = inject(PermissionService);

    public readonly renderResult = input<RenderResult | null>(null);

    protected readonly source = computed<SyncSourceLink | null>(() => {
        const systemRef = this.renderResult()?.object_information?.system_ref;

        if (systemRef?.kind === 'user') {
            return {
                text: `Synced from user #${ systemRef.id }`,
                link: this.canOpen('base.user-management.user.edit') ? ['/management/users/edit', `${ systemRef.id }`] : null
            };
        }

        if (systemRef?.kind === 'user_group') {
            return {
                text: `Synced from user group #${ systemRef.id }`,
                link: this.canOpen('base.user-management.group.edit') ? ['/management/groups/edit', `${ systemRef.id }`] : null
            };
        }

        return null;
    });

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    private canOpen(right: string): boolean {
        return this.permissionService.hasRight(right) || this.permissionService.hasExtendedRight(right);
    }
}
