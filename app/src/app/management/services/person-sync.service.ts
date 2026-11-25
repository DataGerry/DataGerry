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
import { Injectable, inject } from '@angular/core';
import { HttpHeaders, HttpResponse } from '@angular/common/http';
import { Observable, map } from 'rxjs';

import { ApiCallService, resp } from '../../services/api-call.service';
import { APIGetSingleResponse } from '../../services/models/api-response';
import {
    GroupMapping,
    GroupMappingRequest,
    GroupMappingResult,
    GroupSyncSettings,
    SyncPassCounts,
    SyncPassResult,
    UserPerson,
    UserSyncCheck,
    UserSyncPassResult,
    UserSyncRequest,
    UserSyncSettings
} from '../models/person-sync';
/* ------------------------------------------------------------------------------------------------------------------ */

@Injectable({ providedIn: 'root' })
export class PersonSyncService {

    private readonly api = inject(ApiCallService);

    private readonly route = 'person_sync';

    private readonly options = {
        headers: new HttpHeaders({ 'Content-Type': 'application/json' }),
        observe: resp
    };

/* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    public getUserSync(): Observable<UserSyncSettings> {
        return this.api.callGet<APIGetSingleResponse<UserSyncSettings>>(`${ this.route }/users`, this.options)
            .pipe(map((response: HttpResponse<APIGetSingleResponse<UserSyncSettings>>) => response.body.result));
    }


    public updateUserSync(settings: UserSyncRequest): Observable<UserSyncPassResult> {
        return this.api.callPut<UserSyncPassResult>(`${ this.route }/users`, settings, this.options)
            .pipe(map((response: HttpResponse<UserSyncPassResult>) => response.body));
    }


    /** Dry run of a settings change: which persons would change Type and what blocks them. Writes nothing. */
    public checkUserSync(settings: UserSyncRequest): Observable<UserSyncCheck> {
        return this.api.callPost<APIGetSingleResponse<UserSyncCheck>>(`${ this.route }/users/check`, settings, this.options)
            .pipe(map((response: HttpResponse<APIGetSingleResponse<UserSyncCheck>>) => response.body.result));
    }


    public getGroupSync(): Observable<GroupSyncSettings> {
        return this.api.callGet<APIGetSingleResponse<GroupSyncSettings>>(`${ this.route }/groups`, this.options)
            .pipe(map((response: HttpResponse<APIGetSingleResponse<GroupSyncSettings>>) => response.body.result));
    }


    public updateGroupSync(active: boolean): Observable<SyncPassResult<GroupSyncSettings>> {
        return this.api.callPut<SyncPassResult<GroupSyncSettings>>(`${ this.route }/groups`, { active }, this.options)
            .pipe(map((response: HttpResponse<SyncPassResult<GroupSyncSettings>>) => response.body));
    }


    public mapUserGroup(userGroupId: number, request: GroupMappingRequest): Observable<GroupMappingResult> {
        return this.api.callPut<GroupMappingResult>(`${ this.route }/groups/${ userGroupId }`, request, this.options)
            .pipe(map((response: HttpResponse<GroupMappingResult>) => response.body));
    }


    public unmapUserGroup(userGroupId: number): Observable<GroupMapping> {
        return this.api.callDelete<APIGetSingleResponse<GroupMapping>>(`${ this.route }/groups/${ userGroupId }`, this.options)
            .pipe(map((response: HttpResponse<APIGetSingleResponse<GroupMapping>>) => response.body.result));
    }


    /** Reruns the sync over all users and groups on the stored settings; answers only the counts. */
    public resync(): Observable<SyncPassCounts> {
        return this.api.callPost<APIGetSingleResponse<SyncPassCounts>>(`${ this.route }/resync`, null, this.options)
            .pipe(map((response: HttpResponse<APIGetSingleResponse<SyncPassCounts>>) => response.body.result));
    }


    /** The person mirroring a user; person_id is null while it has none. */
    public getUserPerson(userId: number): Observable<UserPerson> {
        return this.api.callGet<APIGetSingleResponse<UserPerson>>(`users/${ userId }/person`, this.options)
            .pipe(map((response: HttpResponse<APIGetSingleResponse<UserPerson>>) => response.body.result));
    }
}
