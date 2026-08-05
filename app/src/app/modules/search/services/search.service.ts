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
import { HttpParams } from '@angular/common/http';

import { Observable, map } from 'rxjs';

import { ApiCallService, ApiServicePrefix, httpObservePostOptions } from '../../../services/api-call.service';
import { ValidatorService } from '../../../services/validator.service';

import { NumberSearchResults, SearchResultList } from '../models/search-result';
/* ------------------------------------------------------------------------------------------------------------------ */

export const COOCKIENAME = 'onlyActiveObjCookie';

@Injectable({
    providedIn: 'root'
})
export class SearchService<T = SearchResultList> implements ApiServicePrefix {

    public servicePrefix: string = 'search';


    public constructor(private api: ApiCallService) {

    }


    public getEstimateValueResults(regex: string): Observable<NumberSearchResults> {
        const httpOptions = httpObservePostOptions;
        let params = new HttpParams();
        params = params.set('searchValue', ValidatorService.validateRegex(regex).trim() );
        httpOptions.params = params;

        return this.api.callGet<NumberSearchResults>(this.servicePrefix + '/quick/count/', httpOptions).pipe(
            map((apiResponse) => {
                return apiResponse.body;
            })
        );
    }


    public postSearch(query: any, params?: HttpParams): Observable<T> {
        const httpOptions = httpObservePostOptions;
        params = params.set('onlyActiveObjCookie', this.api.readCookies(COOCKIENAME));

        if (params) {
            httpOptions.params = params;
        }

        return this.api.callPost<T>(`${ this.servicePrefix }/`, query, httpOptions).pipe(
            map((apiResponse) => {
                if (apiResponse.statusCode === 204) {
                    return [];
                }

                return apiResponse.body;
            })
        );
    }
}