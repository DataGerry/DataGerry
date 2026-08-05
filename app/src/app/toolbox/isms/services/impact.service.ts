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
import { HttpHeaders, HttpParams, HttpResponse } from '@angular/common/http';
import { Observable } from 'rxjs';
import { catchError, map } from 'rxjs/operators';

import { ApiServicePrefix, resp, ApiCallService } from 'src/app/services/api-call.service';
import { CollectionParameters } from 'src/app/services/models/api-parameter';
import {
  APIGetMultiResponse,
  APIInsertSingleResponse,
  APIUpdateSingleResponse,
  APIDeleteSingleResponse
} from 'src/app/services/models/api-response';

import { Impact } from '../models/impact.model';

@Injectable({
  providedIn: 'root'
})
export class ImpactService<T = any> implements ApiServicePrefix {
  public servicePrefix: string = 'isms/impacts';

  public options = {
    headers: new HttpHeaders({ 'Content-Type': 'application/json' }),
    params: {},
    observe: resp
  };

  constructor(private api: ApiCallService) {}

  /**
   * Fetch a paginated list of impact entries.
   */
  public getImpacts(
    params: CollectionParameters = {
      filter: '',
      limit: 10,
      sort: 'name',
      order: 1,
      page: 1
    }
  ): Observable<APIGetMultiResponse<Impact>> {
    const options = { ...this.options };
    let httpParams = new HttpParams();

    if (params.filter !== undefined) {
      const filter = JSON.stringify(params.filter);
      httpParams = httpParams.set('filter', filter);
    }

    httpParams = httpParams.set('limit', params.limit.toString());
    httpParams = httpParams.set('sort', params.sort);
    httpParams = httpParams.set('order', params.order.toString());
    httpParams = httpParams.set('page', params.page.toString());
    options.params = httpParams;

    return this.api.callGet<APIGetMultiResponse<Impact>>(`${this.servicePrefix}/`, options)
      .pipe(
        map((res: HttpResponse<APIGetMultiResponse<Impact>>) => res.body),
        catchError((error) => {
          throw error;
        })
      );
  }

  /**
   * Create a new impact entry.
   */
  public createImpact(data: Partial<Impact>): Observable<APIInsertSingleResponse<T>> {
    const options = { ...this.options };

    return this.api.callPost<APIInsertSingleResponse<T>>(`${this.servicePrefix}/`, data, options)
      .pipe(
        map((res: HttpResponse<APIInsertSingleResponse<T>>) => res.body),
        catchError((error) => {
          throw error;
        })
      );
  }

  /**
   * Update an existing impact entry by its public ID.
   */
  public updateImpact(publicId: number, data: Partial<Impact>): Observable<APIUpdateSingleResponse<T>> {
    const options = { ...this.options };

    // If your API requires public_id in the body, you can do:
    const body = { public_id: publicId, ...data };

    return this.api.callPut<APIUpdateSingleResponse<T>>(`${this.servicePrefix}/${publicId}`, body, options)
      .pipe(
        map((res: HttpResponse<APIUpdateSingleResponse<T>>) => res.body),
        catchError((error) => {
          throw error;
        })
      );
  }

  /**
   * Delete an impact entry by its public ID.
   */
  public deleteImpact(publicId: number): Observable<APIDeleteSingleResponse<T>> {
    const options = { ...this.options };
    options.params = new HttpParams();

    return this.api.callDelete<APIDeleteSingleResponse<T>>(`${this.servicePrefix}/${publicId}`, options)
      .pipe(
        map((res: HttpResponse<APIDeleteSingleResponse<T>>) => res.body),
        catchError((error) => {
          throw error;
        })
      );
  }
}
