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
import { ActivatedRouteSnapshot, Router, RouterStateSnapshot, UrlTree } from '@angular/router';

import { Observable } from 'rxjs';

import { PermissionService } from '../services/permission.service';
/* ------------------------------------------------------------------------------------------------------------------ */
@Injectable({
    providedIn: 'root'
})
export class PermissionGuard  {

    public constructor(
        private permissionService: PermissionService,
        private router: Router
    ) {

    }


    public canActivate(next: ActivatedRouteSnapshot, state: RouterStateSnapshot):
        Observable<boolean | UrlTree> | Promise<boolean | UrlTree> | boolean | UrlTree {
            const right: string = next.data.right as string;
            return this.resolveAccess(right);
    }


    public canActivateChild(childRoute: ActivatedRouteSnapshot, state: RouterStateSnapshot):
        Observable<boolean | UrlTree> | Promise<boolean | UrlTree> | boolean | UrlTree {
            const right: string = childRoute.data.right as string;
            return this.resolveAccess(right);
    }


    /** Sends a denied navigation to the forbidden page instead of leaving an empty router outlet */
    private resolveAccess(right: string): boolean | UrlTree {
        return this.hasRequiredPermission(right) ? true : this.router.parseUrl('/error/403');
    }


    public hasRequiredPermission(right: string): boolean {
        if (right === undefined || this.permissionService.hasRight(right)) {
            return true;
        } else {
            return this.permissionService.hasExtendedRight(right);
        }
    }
}