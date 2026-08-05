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
import { HttpParams, HttpResponse } from '@angular/common/http';

import { Observable } from 'rxjs';
import { map } from 'rxjs/operators';

import { ApiCallService, ApiServicePrefix, httpObserveOptions } from '../../services/api-call.service';

import { CmdbLink } from '../models/cmdb-link';
import { APIDeleteSingleResponse,
         APIGetMultiResponse,
         APIInsertSingleResponse } from '../../services/models/api-response';
import { CollectionParameters } from '../../services/models/api-parameter';
/* ------------------------------------------------------------------------------------------------------------------ */

@Injectable({
  providedIn: 'root'
})
export class LinkService<T = CmdbLink> implements ApiServicePrefix {

  public readonly servicePrefix: string = 'objects/links';

  constructor(private api: ApiCallService) {
  }

/* -------------------------------------------------- CRUD - CREATE ------------------------------------------------- */

    /**
     * Add a new link.
     * @param data
     */
    public postLink(data: CmdbLink): Observable<any> {
        const options = httpObserveOptions;
        options.params = new HttpParams();

        return this.api.callPost<CmdbLink>(`${ this.servicePrefix }/`, data, options).pipe(
            map((apiResponse: HttpResponse<APIInsertSingleResponse<T>>) => {
                return apiResponse.body.raw as T;
            })
        );
    }

/* --------------------------------------------------- CRUD - READ -------------------------------------------------- */

    /**
     * Get the partners public id on a link
     * @param objectID
     * @param link
     */
    public getPartnerID(objectID: number, link: CmdbLink): number {
        return objectID === link.primary ? link.secondary : link.primary;
    }


    /**
     * Iterate over the links collection by a specific id
     * @param objectID public_id of object link
     * @param params Instance of CollectionParameters
     */
    public getPartnerLinks(objectID: number, params: CollectionParameters = {
        filter: undefined,
        limit: 10,
        sort: 'public_id',
        order: 1,
        page: 1
    }): Observable<APIGetMultiResponse<T>> {
        const options = httpObserveOptions;
        let httpParams: HttpParams = new HttpParams();

        const filter = JSON.stringify({
            $or: [{ primary: objectID }, { secondary: objectID }]
        });

        httpParams = httpParams.set('filter', filter);
        httpParams = httpParams.set('limit', params.limit.toString());
        httpParams = httpParams.set('sort', params.sort);
        httpParams = httpParams.set('order', params.order.toString());
        httpParams = httpParams.set('page', params.page.toString());
        options.params = httpParams;

        return this.api.callGet<Array<T>>(this.servicePrefix + '/', options).pipe(
            map((apiResponse: HttpResponse<APIGetMultiResponse<T>>) => {
                return apiResponse.body;
            })
        );
    }

/* -------------------------------------------------- CRUD - DELETE ------------------------------------------------- */

    /**
     * Delete an existing object link
     * @param publicID public_id of the object link
     */
    public deleteLink(publicID: number): Observable<any> {
        const options = httpObserveOptions;
        options.params = new HttpParams();
        return this.api.callDelete<number>(`${ this.servicePrefix }/${ publicID }`, options).pipe(
            map((apiResponse: HttpResponse<APIDeleteSingleResponse<T>>) => {
                return apiResponse.body;
            })
        );
    }
}
