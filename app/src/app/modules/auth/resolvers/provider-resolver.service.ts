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
import { Injectable } from '@angular/core';
import { ActivatedRouteSnapshot, RouterStateSnapshot } from '@angular/router';

import { Observable } from 'rxjs';

import { AuthService } from '../services/auth.service';

import { AuthProvider } from '../models/providers';
/* ------------------------------------------------------------------------------------------------------------------ */
@Injectable({
    providedIn: 'root'
})
export class ProviderResolver  {

    constructor(private authService: AuthService) {

    }


    resolve(route: ActivatedRouteSnapshot, state: RouterStateSnapshot):
        Observable<Array<AuthProvider>> | Promise<Array<AuthProvider>> | Array<AuthProvider> {
            return this.authService.getProviders();
    }
}
