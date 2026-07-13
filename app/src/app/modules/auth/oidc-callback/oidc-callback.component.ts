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
import { Component, OnInit } from '@angular/core';
import { Router } from '@angular/router';

import { first } from 'rxjs';

import { AuthService } from '../services/auth.service';
import { PermissionService } from '../services/permission.service';
import { UserSettingsDBService } from '../../../management/user-settings/services/user-settings-db.service';

import { Token } from '../models/token';
import { User } from '../../../management/models/user';

@Component({
    selector: 'cmdb-oidc-callback',
    template: `
        <div class="d-flex justify-content-center align-items-center" style="height: 100vh;">
            <div class="text-center">
                <div class="spinner-border text-primary" role="status">
                    <span class="sr-only">Completing authentication...</span>
                </div>
                <p class="mt-3">Completing authentication...</p>
            </div>
        </div>
    `,
    standalone: false
})
export class OidcCallbackComponent implements OnInit {

    constructor(
        private router: Router,
        private authService: AuthService,
        private permissionService: PermissionService,
        private userSettingsDB: UserSettingsDBService
    ) {}

    public ngOnInit(): void {
        // FIX 1: PathLocationStrategy means a single '#'; the fragment holds the form-urlencoded params.
        const fragment = window.location.hash.startsWith('#') ? window.location.hash.substring(1) : '';
        const params = new URLSearchParams(fragment);

        // FIX 2: strip the token from the URL/history immediately so it is not retained.
        history.replaceState(null, document.title, window.location.pathname);

        const tokenStr = params.get('token');
        const userStr = params.get('user');

        if (tokenStr && userStr) {
            try {
                const user: User = JSON.parse(userStr);
                // FIX 3: use the real token issue/expiry so SessionTimeoutService works correctly.
                const token: Token = {
                    token: tokenStr,
                    issued: Number(params.get('token_issued_at')),
                    expire: Number(params.get('token_expire'))
                };

                this.authService.applyExternalLogin(user, token);
                this.userSettingsDB.syncSettings();

                this.permissionService.storeUserRights(user.group_id)
                    .pipe(first())
                    .subscribe({
                        next: () => this.router.navigate(['/']),
                        error: () => this.router.navigate(['/'])
                    });
            } catch (err) {
                this.router.navigate(['/auth'], {
                    queryParams: { error: 'Failed to process OIDC callback', local: true }
                });
            }
        } else {
            const error = params.get('error');
            this.router.navigate(['/auth'], {
                queryParams: { error: error || 'OIDC authentication failed', local: true }
            });
        }
    }
}
