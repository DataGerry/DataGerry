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

* You should have received a copy of the GNU Affero General Public License
* along with this program.  If not, see <https://www.gnu.org/licenses/>.
*/

import { Injectable } from '@angular/core';
import { ApiCallService, ApiServicePrefix, httpObserveOptions } from '../../services/api-call.service';
import { Right, SecurityLevel } from '../models/right';
import { Observable } from 'rxjs';
import { map } from 'rxjs/operators';
import { HttpParams, HttpResponse } from '@angular/common/http';
import { APIGetMultiResponse, APIGetSingleResponse } from '../../services/models/api-response';
import { CollectionParameters } from '../../services/models/api-parameter';

@Injectable({
  providedIn: 'root'
})
export class RightService<T = Right> implements ApiServicePrefix {

  public readonly servicePrefix: string = 'rights';

  constructor(private api: ApiCallService) {
  }

  /**
   * Iterate over the right collection
   * @param params Instance of CollectionParameters
   */
  public getRights(params: CollectionParameters = { filter: undefined, limit: 10, sort: 'name', order: 1, page: 1 }
  ): Observable<APIGetMultiResponse<T>> {
    const options = httpObserveOptions;
    let httpParams: HttpParams = new HttpParams();
    if (params.filter !== undefined) {
      httpParams = httpParams.set('filter', params.filter);
    }
    httpParams = httpParams.set('limit', params.limit.toString());
    httpParams = httpParams.set('sort', params.sort);
    httpParams = httpParams.set('order', params.order.toString());
    httpParams = httpParams.set('page', params.page.toString());
    options.params = httpParams;
    return this.api.callGet<T>(`${ this.servicePrefix }/`, options).pipe(
      map((apiResponse: HttpResponse<APIGetMultiResponse<T>>) => {
        return apiResponse.body;
      })
    );
  }

  /**
   * Get a right by its name.
   * @param name: Name of the right.
   */
  public getRight(name: string): Observable<T> {
    const options = httpObserveOptions;
    options.params = new HttpParams();
    return this.api.callGet<T>(`${ this.servicePrefix }/${ name }`, options).pipe(
      map((apiResponse: HttpResponse<APIGetSingleResponse<T>>) => {
        return apiResponse.body.result as T;
      })
    );
  }

  /**
   * Get security levels from backend.
   * Should be the same as the SecurityLevel Enum.
   */
  public getLevels(): Observable<SecurityLevel> {
    const options = httpObserveOptions;
    options.params = new HttpParams();
    return this.api.callGet<T>(`${ this.servicePrefix }/levels`, options).pipe(
      map((apiResponse: HttpResponse<APIGetSingleResponse<SecurityLevel>>) => {
        return apiResponse.body.result as SecurityLevel;
      })
    );
  }
}
