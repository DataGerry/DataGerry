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
import { Component, OnInit } from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import { AuthService } from '../services/auth.service';
import { UserSettingsDB } from '../../../shared/services/user-settings-db.service';

@Component({
    selector: 'app-auth-callback',
    template: '<div class="d-flex justify-content-center align-items-center vh-100"><div class="spinner-border text-primary" role="status"><span class="visually-hidden">Loading...</span></div></div>',
    standalone: false
})
export class AuthCallbackComponent implements OnInit {

    constructor(
        private route: ActivatedRoute,
        private router: Router,
        private authService: AuthService,
        private userSettingsDB: UserSettingsDB
    ) { }

    ngOnInit(): void {
        this.route.queryParams.subscribe(params => {
            const token = params['token'];
            const expires = params['expires'];
            const error = params['error'];

            if (error) {
                console.error('Authentication error:', error);
                this.router.navigate(['/auth/login'], { queryParams: { error: error } });
                return;
            }

            if (token && expires) {
                // Process the token
                this.authService.handleEntraIdCallback(token, parseInt(expires, 10));

                // Sync user settings and navigate home
                this.userSettingsDB.syncSettings();
                this.router.navigate(['/']);
            } else {
                console.error('Missing token or expiration');
                this.router.navigate(['/auth/login']);
            }
        });
    }
}
