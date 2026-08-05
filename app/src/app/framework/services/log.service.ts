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
import { ApiCallService, ApiServicePrefix, httpObserveOptions, HttpProtocolHelper } from '../../services/api-call.service';
import { Observable } from 'rxjs';
import { map } from 'rxjs/operators';
import { CmdbLog } from '../models/cmdb-log';
import { CollectionParameters } from '../../services/models/api-parameter';
import { APIGetMultiResponse } from '../../services/models/api-response';
import { HttpResponse } from '@angular/common/http';
import { User } from '../../management/models/user';

export interface LogUserMap {
  [publicId: number]: Partial<User>;
}

export type APILogsWithUsersResponse<T = CmdbLog> = Omit<APIGetMultiResponse<T>, 'results'> & {
  results: {
    logs: Array<T>;
    users: LogUserMap;
  };
};

@Injectable({
  providedIn: 'root'
})
export class LogService<T = CmdbLog> implements ApiServicePrefix {

  constructor(private api: ApiCallService) {
  }

  public servicePrefix: string = 'logs';




  public getLog(publicID: number): Observable<T> {
    return this.api.callGet<T>(`${this.servicePrefix}/${publicID}`).pipe(
      map((apiResponse) => {
        return apiResponse.body;
      })
    );
  }



  /**
   * Iterate over the log collection
   * @param publicID
   * @param params Instance of CollectionParameters
   */
  public getLogsByObject(publicID: number, params: CollectionParameters = {
    filter: undefined,
    limit: 10, sort: 'public_id', order: 1, page: 1
  }): Observable<APIGetMultiResponse<T>> {
    const options = HttpProtocolHelper.createHttpProtocolOptions(httpObserveOptions,
      JSON.stringify(params.filter), params.limit, params.sort, params.order, params.page);
    return this.api.callGet<Array<T>>(`${this.servicePrefix}/object/${publicID}`, options).pipe(
      map((apiResponse: HttpResponse<APIGetMultiResponse<T>>) => {
        return apiResponse.body;
      })
    );
  }



  public getLogsWithExistingObject(params: CollectionParameters = {
    filter: undefined,
    limit: 10, sort: 'public_id', order: 1, page: 1
  }): Observable<APILogsWithUsersResponse<T>> {
    const options = HttpProtocolHelper.createHttpProtocolOptions(httpObserveOptions, params.filter,
      params.limit, params.sort, params.order, params.page);
    options.params = options.params.set('include_users', 'true');

    return this.api.callGet<Array<T>>(`${this.servicePrefix}/object/exists`, options).pipe(
      map((apiResponse: HttpResponse<APILogsWithUsersResponse<T>>) => {
        return apiResponse.body;
      })
    );
  }



  public getLogsWithNotExistingObject(params: CollectionParameters = {
    filter: undefined,
    limit: 10, sort: 'public_id', order: 1, page: 1
  }): Observable<APILogsWithUsersResponse<T>> {
    const options = HttpProtocolHelper.createHttpProtocolOptions(httpObserveOptions, params.filter,
      params.limit, params.sort, params.order, params.page);
    options.params = options.params.set('include_users', 'true');

    return this.api.callGet<T>(`${this.servicePrefix}/object/notexists`, options).pipe(
      map((apiResponse: HttpResponse<APILogsWithUsersResponse<T>>) => {
        return apiResponse.body;
      })
    );
  }



  public getDeleteLogs(params: CollectionParameters = {
    filter: undefined,
    limit: 10, sort: 'public_id', order: 1, page: 1
  }): Observable<APILogsWithUsersResponse<T>> {
    const options = HttpProtocolHelper.createHttpProtocolOptions(httpObserveOptions, params.filter,
      params.limit, params.sort, params.order, params.page);
    options.params = options.params.set('include_users', 'true');

    return this.api.callGet<T>(`${this.servicePrefix}/object/deleted`, options).pipe(
      map((apiResponse: HttpResponse<APILogsWithUsersResponse<T>>) => {
        return apiResponse.body;
      })
    );
  }



  public getCorrespondingLogs(publicID: number) {
    return this.api.callGet<T>(`${this.servicePrefix}/${publicID}/corresponding`).pipe(
      map((apiResponse) => {
        if (apiResponse.status === 204) {
          return [];
        }
        return apiResponse.body;
      })
    );
  }



  public deleteLog(publicID: number): Observable<T> {
    return this.api.callDelete<boolean>(`${this.servicePrefix}/${publicID}`).pipe(
      map((apiResponse) => {
        return apiResponse.body;
      })
    );
  }
}
