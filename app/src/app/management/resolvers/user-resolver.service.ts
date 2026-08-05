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

import { UserService } from '../services/user.service';
import { AuthService } from '../../modules/auth/services/auth.service';

import { User } from '../models/user';
/* ------------------------------------------------------------------------------------------------------------------ */

@Injectable({
  providedIn: 'root'
})
export class OwnUserResolver  {

    constructor(private authService: AuthService, private userService: UserService) {

    }


    public resolve(route: ActivatedRouteSnapshot, state: RouterStateSnapshot): Observable<User> | Promise<User> | User {
        const userID: number = +this.authService.currentUserValue.public_id;
        return this.userService.getUser(userID);
    }
}


@Injectable({
  providedIn: 'root'
})
export class UserResolver  {

    constructor(private userService: UserService) {

    }


    public resolve(route: ActivatedRouteSnapshot, state: RouterStateSnapshot): Observable<User> | Promise<User> | User {
        const userID: number = +route.paramMap.get('publicID');
        return this.userService.getUser(userID);
    }
}