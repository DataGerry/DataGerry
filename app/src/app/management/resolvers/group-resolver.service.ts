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

import { Observable, forkJoin, map, of } from 'rxjs';

import { GroupService } from '../services/group.service';
import { AuthService } from '../../modules/auth/services/auth.service';

import { Group } from '../models/group';
import { APIGetMultiResponse } from '../../services/models/api-response';
import { CollectionParameters } from '../../services/models/api-parameter';
/* ------------------------------------------------------------------------------------------------------------------ */

@Injectable({
  providedIn: 'root'
})
export class OwnGroupsResolver  {

    constructor(private authService: AuthService, private groupService: GroupService) {

    }


    public resolve(route: ActivatedRouteSnapshot, state: RouterStateSnapshot): Observable<Group[]> {
        const groupIDs: number[] = this.authService.currentUserValue?.group_ids ?? [];
        // forkJoin of nothing never emits, which would cancel the navigation.
        return groupIDs.length ? forkJoin(groupIDs.map(groupID => this.groupService.getGroup(groupID))) : of([]);
    }
}


/**
 * Resolver for a single group
 */
@Injectable({
  providedIn: 'root'
})
export class GroupResolver  {

    constructor(private groupService: GroupService) {

    }


    public resolve(route: ActivatedRouteSnapshot, state: RouterStateSnapshot): Observable<Group> | Promise<Group> | Group {
        const groupID: number = +route.paramMap.get('publicID');
        return this.groupService.getGroup(groupID);
    }
}


/**
 * Resolver for all groups
 */
@Injectable({
  providedIn: 'root'
})
export class GroupsResolver  {

    constructor(private groupService: GroupService) {

    }


    public resolve(route: ActivatedRouteSnapshot, state: RouterStateSnapshot):
        Observable<Array<Group>> | Promise<Array<Group>> | Array<Group> {
            const params: CollectionParameters = {
                filter: undefined,
                limit: 0,
                sort: 'public_id',
                order: 1,
                page: 1
            };

            return this.groupService.getGroups(params).pipe(map((response: APIGetMultiResponse<Group>) => {
                return response.results as Array<Group>;
            }));
    }
}