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

import { Observable, map } from 'rxjs';

import { RightService } from '../services/right.service';

import { Right } from '../models/right';
import { APIGetMultiResponse } from '../../services/models/api-response';
/* ------------------------------------------------------------------------------------------------------------------ */

/**
 * Resolver for the complete right list
 */
@Injectable({
  providedIn: 'root'
})
export class RightsResolver  {

    constructor(private rightService: RightService) {

    }


    resolve(route: ActivatedRouteSnapshot, state: RouterStateSnapshot): Observable<Array<Right>> | Promise<Array<Right>> | Array<Right> {
        return this.rightService.getRights({ filter: undefined, limit: 0, sort: 'name', order: 1, page: 1 }).pipe(
            map((
                apiResponse: APIGetMultiResponse<Right>) => {
                    return apiResponse.results as Array<Right>;
            })
        );
    }
}
