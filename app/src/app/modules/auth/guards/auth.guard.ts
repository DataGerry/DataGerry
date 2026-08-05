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
import { ActivatedRouteSnapshot, RouterStateSnapshot, UrlTree, Router } from '@angular/router';

import { Observable } from 'rxjs';

import { AuthService } from '../services/auth.service';
/* ------------------------------------------------------------------------------------------------------------------ */
@Injectable({
    providedIn: 'root'
})
export class AuthGuard  {

    constructor(
        private router: Router,
        private authService: AuthService
    ) {

    }


    public canActivate(next: ActivatedRouteSnapshot, state: RouterStateSnapshot):
        Observable<boolean | UrlTree> | Promise<boolean | UrlTree> | boolean | UrlTree {
            return this.checkUser();
    }


    public canActivateChild(childRoute: ActivatedRouteSnapshot, state: RouterStateSnapshot):
        Observable<boolean | UrlTree> | Promise<boolean | UrlTree> | boolean | UrlTree {
            return this.checkUser(true);
    }


    /**
     * Checks if user exists
     * @param navigate (boolean): True if user should be navigated to login page
     * @returns True if User exists, else False
     */
    private checkUser(navigate: boolean = false) {
        const currentUser = this.authService.currentUserValue;
        const currentUserToken = this.authService.currentUserTokenValue;

        if (currentUser && currentUserToken) {
            return true;
        }

        this.authService.logout();

        if(navigate){
            this.router.navigate(['auth']);
        }

        return false;
    }
}
