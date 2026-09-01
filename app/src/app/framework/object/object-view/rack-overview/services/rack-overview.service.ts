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
import { HttpHeaders, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { finalize, map } from 'rxjs/operators';

import { ApiCallService, resp } from '../../../../../services/api-call.service';
import { CollectionParameters } from '../../../../../services/models/api-parameter';
import {
    APIDeleteSingleResponse,
    APIGetMultiResponse,
    APIInsertSingleResponse,
    APIUpdateSingleResponse
} from '../../../../../services/models/api-response';
import { LocationService } from '../../../../services/location.service';
import { COOCKIENAME as OBJECT_ACTIVE_COOKIE } from '../../../../services/object.service';
import {
    RackArea,
    RackAssignableObject,
    RackHeightConflictsResponse,
    RackMount,
    RackMountPayload,
    RackMountRow,
    RackMountUpdatePayload,
    RackMountValidatePayload,
    RackMountValidationResponse,
    RackOverviewResponse
} from '../models/rack-overview.types';
/* ------------------------------------------------------------------------------------------------------------------ */


@Injectable({ providedIn: 'root' })
export class RackOverviewService {

    public servicePrefix = 'racks';

    private readonly api = inject(ApiCallService);
    private readonly locationService = inject(LocationService);

    private readonly jsonHeaders = new HttpHeaders({ 'Content-Type': 'application/json' });

    /* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    public getOverview(rackId: number): Observable<RackOverviewResponse> {
        return this.api
            .callGet<RackOverviewResponse>(`${this.servicePrefix}/${rackId}/overview`, this.requestOptions())
            .pipe(map(response => response?.body as RackOverviewResponse));
    }


    /** Raw membership list of a rack, optionally narrowed to one area. No object resolution. */
    public getMounts(rackId: number, area?: RackArea): Observable<RackMount[]> {
        const options = {
            ...this.requestOptions(),
            params: area ? new HttpParams().set('area', area) : {}
        };

        return this.api
            .callGet<RackMount[]>(`${this.servicePrefix}/${rackId}/mounts/`, options)
            .pipe(map(response => (response?.body as RackMount[]) ?? []));
    }


    /**
     * Answers "where is this object mounted?". An object belongs to at most one rack, so this is a
     * single mount or null - the mount lives in its own collection, not on the object.
     */
    public getMountOfObject(objectId: number): Observable<RackMount | null> {
        return this.api
            .callGet<RackMount | null>(`${this.servicePrefix}/mounts/object/${objectId}`, this.requestOptions())
            .pipe(map(response => (response?.body as RackMount) ?? null));
    }


    /**
     * The objects this rack can take. Membership rules are applied server side, so the picker never
     * has to filter racks out of the list itself. Objects mounted in another rack are included and
     * flagged with that rack; `onlyUnmounted` narrows the list to objects that are free.
     */
    public getAssignableObjects(
        rackId: number,
        params: CollectionParameters = { filter: undefined, limit: 10, sort: 'public_id', order: 1, page: 1 },
        onlyUnmounted = false
    ): Observable<APIGetMultiResponse<RackAssignableObject>> {
        let httpParams = new HttpParams();

        if (params.filter !== undefined) {
            httpParams = httpParams.set('filter', JSON.stringify(params.filter));
        }

        httpParams = httpParams.set('only_unmounted', String(onlyUnmounted));
        httpParams = httpParams.set('limit', String(params.limit));
        httpParams = httpParams.set('sort', params.sort);
        httpParams = httpParams.set('order', String(params.order));
        httpParams = httpParams.set('page', String(params.page));
        httpParams = httpParams.set('onlyActiveObjCookie', this.api.readCookies(OBJECT_ACTIVE_COOKIE));

        const options = { ...this.requestOptions(), params: httpParams };

        return this.api
            .callGet<APIGetMultiResponse<RackAssignableObject>>(
                `${this.servicePrefix}/${rackId}/assignable_objects/`,
                options
            )
            .pipe(map(response => response?.body as APIGetMultiResponse<RackAssignableObject>));
    }


    /**
     * Pre-check behind "shrinking this rack would displace these objects". Purely informational: the
     * height change unplaces them whether or not this was called.
     */
    public getHeightConflicts(rackId: number, height: number): Observable<RackHeightConflictsResponse> {
        const options = {
            ...this.requestOptions(),
            params: new HttpParams().set('height', String(height))
        };

        return this.api
            .callGet<RackHeightConflictsResponse>(`${this.servicePrefix}/${rackId}/height_conflicts`, options)
            .pipe(map(response => response?.body as RackHeightConflictsResponse));
    }


    /** Dry run of a placement. Answers with the reasons a mount would be refused, and writes nothing. */
    public validateMount(rackId: number, payload: RackMountValidatePayload): Observable<RackMountValidationResponse> {
        return this.api
            .callPost<RackMountValidationResponse>(
                `${this.servicePrefix}/${rackId}/mounts/validate`,
                payload,
                this.requestOptions()
            )
            .pipe(map(response => response?.body as RackMountValidationResponse));
    }


    /** The backend mirrors a mount into the location tree, so the three writes below announce it. */
    public mountObject(rackId: number, payload: RackMountPayload): Observable<APIInsertSingleResponse<RackMountRow>> {
        return this.api
            .callPost<APIInsertSingleResponse<RackMountRow>>(
                `${this.servicePrefix}/${rackId}/mounts/`,
                payload,
                this.requestOptions()
            )
            .pipe(
                map(response => response?.body as APIInsertSingleResponse<RackMountRow>),
                finalize(() => this.locationService.executedAction('update'))
            );
    }


    /** Places, moves, resizes, reorders or unplaces an existing mount. */
    public updateMount(
        rackId: number,
        mountId: number,
        payload: RackMountUpdatePayload
    ): Observable<APIUpdateSingleResponse<RackMountRow>> {
        return this.api
            .callPatch<APIUpdateSingleResponse<RackMountRow>>(
                `${this.servicePrefix}/${rackId}/mounts/${mountId}`,
                payload,
                this.requestOptions()
            )
            .pipe(
                map(response => response?.body as APIUpdateSingleResponse<RackMountRow>),
                finalize(() => this.locationService.executedAction('update'))
            );
    }


    /** Removes the membership only. The mounted object itself is never touched. */
    public deleteMount(rackId: number, mountId: number): Observable<APIDeleteSingleResponse<RackMountRow>> {
        return this.api
            .callDelete<APIDeleteSingleResponse<RackMountRow>>(
                `${this.servicePrefix}/${rackId}/mounts/${mountId}`,
                this.requestOptions()
            )
            .pipe(
                map(response => response?.body as APIDeleteSingleResponse<RackMountRow>),
                finalize(() => this.locationService.executedAction('update'))
            );
    }

    /* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    private requestOptions() {
        return {
            headers: this.jsonHeaders,
            params: {},
            observe: resp
        };
    }
}
