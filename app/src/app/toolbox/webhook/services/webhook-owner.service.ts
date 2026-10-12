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
import { inject, Injectable } from '@angular/core';
import { catchError, map, Observable, of } from 'rxjs';

import { UserService } from 'src/app/management/services/user.service';
import { User } from 'src/app/management/models/user';
import { PermissionService } from 'src/app/modules/auth/services/permission.service';
import { Webhook, WebhookOwner, WebhookRow } from '../models/webhook.model';

const USER_VIEW_RIGHT = 'base.user-management.user.view';

@Injectable({
    providedIn: 'root',
})
export class WebhookOwnerService {
    private readonly userService = inject(UserService);
    private readonly permissionService = inject(PermissionService);

    /* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    /** Without the user view right only the current user can be named. */
    public withOwners(webhooks: Webhook[]): Observable<WebhookRow[]> {
        const ownerIds = [...new Set(webhooks.map(webhook => webhook.owner_id).filter(this.isUserId))];

        if (!ownerIds.length || !this.canViewUsers()) {
            return of(webhooks.map(webhook => ({ ...webhook, owner: this.describeOwner(webhook.owner_id) })));
        }

        return this.userService.getUsers({
            filter: { public_id: { $in: ownerIds } },
            limit: ownerIds.length,
            sort: 'public_id',
            order: 1,
            page: 1,
        }).pipe(
            map(response => new Map((response?.results ?? []).map(user => [user.public_id, user]))),
            map(users => webhooks.map(webhook => ({
                ...webhook,
                owner: this.describeOwner(webhook.owner_id, users),
            }))),
            catchError(() => of(webhooks.map(webhook => ({ ...webhook, owner: this.describeOwner(webhook.owner_id) }))))
        );
    }


    public isCurrentUserOwner(webhook: Pick<Webhook, 'owner_id'>): boolean {
        return this.isUserId(webhook.owner_id) && webhook.owner_id === this.userService.getCurrentUser()?.public_id;
    }

    /* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    /** `users` is only passed when the lookup ran, so a missing entry means the user was deleted. */
    private describeOwner(ownerId: number | null | undefined, users?: Map<number, User>): WebhookOwner {
        if (!this.isUserId(ownerId)) {
            return { status: 'none', label: 'No owner' };
        }

        const currentUser = this.userService.getCurrentUser();
        const user = users?.get(ownerId) ?? (currentUser?.public_id === ownerId ? currentUser : undefined);

        if (user) {
            return { status: user.active === false ? 'inactive' : 'active', label: user.user_name };
        }

        if (users) {
            return { status: 'deleted', label: `Deleted user #${ownerId}` };
        }

        return { status: 'unresolved', label: `User #${ownerId}` };
    }


    private canViewUsers(): boolean {
        return this.permissionService.hasRight(USER_VIEW_RIGHT) || this.permissionService.hasExtendedRight(USER_VIEW_RIGHT);
    }


    private isUserId(ownerId: number | null | undefined): ownerId is number {
        return typeof ownerId === 'number';
    }
}
