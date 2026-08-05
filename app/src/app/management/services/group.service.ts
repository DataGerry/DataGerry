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
* along with this program. If not, see <https://www.gnu.org/licenses/>.
*/

import { Injectable } from '@angular/core';
import {
  ApiCallService,
  ApiServicePrefix,
  resp
} from '../../services/api-call.service';
import { Group } from '../models/group';
import { Observable, timer } from 'rxjs';
import { catchError, map, switchMap } from 'rxjs/operators';
import { HttpHeaders, HttpParams, HttpResponse } from '@angular/common/http';
import { UntypedFormControl } from '@angular/forms';
import { CollectionParameters } from '../../services/models/api-parameter';
import {
  APIGetMultiResponse,
  APIGetSingleResponse,
  APIInsertSingleResponse,
  APIUpdateSingleResponse
} from '../../services/models/api-response';

export const groupNameExistsValidator = (groupService: GroupService, time: number = 500) => {
  return (control: UntypedFormControl) => {
    return timer(time).pipe(switchMap(() => {
      return groupService.getGroupByName(control.value).pipe(
        map((response) => {
          if (response === null) {
            return null;
          } else {
            return { groupNameExists: true };
          }
        }),
        catchError(() => {
          return new Promise(resolve => {
            resolve(null);
          });
        })
      );
    }));
  };
};

@Injectable({
  providedIn: 'root'
})
export class GroupService<T = Group> implements ApiServicePrefix {

  public servicePrefix: string = 'groups';

  public readonly post = {
    headers: new HttpHeaders({
      'Content-Type': 'application/json'
    }),
    params: {},
    observe: resp
  };

  constructor(private api: ApiCallService) {
  }

  /**
   * Iterate over a the complete group collection.
   * @param params CollectionParameters for the iteration.
   */
  public getGroups(params: CollectionParameters = {
    filter: undefined, limit: 10, sort: 'public_id', order: 1, page: 1
  }): Observable<APIGetMultiResponse<T>> {
    const options = this.post;
    let httpParams: HttpParams = new HttpParams();
    if (params.filter !== undefined) {
      const filter = JSON.stringify(params.filter);
      httpParams = httpParams.set('filter', filter);
    }
    httpParams = httpParams.set('limit', params.limit.toString());
    httpParams = httpParams.set('sort', params.sort);
    httpParams = httpParams.set('order', params.order.toString());
    httpParams = httpParams.set('page', params.page.toString());
    options.params = httpParams;
    return this.api.callGet<Array<T>>(`${ this.servicePrefix }/`, options).pipe(
      map((apiResponse: HttpResponse<APIGetMultiResponse<T>>) => {
        return apiResponse.body;
      })
    );
  }

  /**
   * Get a single group by its public id.
   * @param publicID: ID of the Group.
   */
  public getGroup(publicID: number): Observable<T> {
    return this.api.callGet<T>(this.servicePrefix + '/' + publicID).pipe(
      map((apiResponse: HttpResponse<APIGetSingleResponse<T>>) => {
        return apiResponse.body.result as T;
      })
    );
  }

  /**
   * Get a group by its name.
   * @param name: Name property of the selected group.
   */
  public getGroupByName(name: string): Observable<T> {
    const options = this.post;
    const filter = { name };
    let params: HttpParams = new HttpParams();
    params = params.set('filter', JSON.stringify(filter));
    options.params = params;
    return this.api.callGet<Array<T>>(`${ this.servicePrefix }/`, options).pipe(
      map((apiResponse: HttpResponse<APIGetMultiResponse<T>>) => {
        if (apiResponse.body.count === 0) {
          return null;
        }
        return apiResponse.body.results[0] as T;
      })
    );
  }

  /**
   * Insert a new group.
   * @param group: Data of the group.
   */
  public postGroup(group: T): Observable<T> {
    const options = this.post;
    options.params = new HttpParams();
    return this.api.callPost<T>(`${ this.servicePrefix }/`, group, options).pipe(
      map((apiResponse: HttpResponse<APIInsertSingleResponse<T>>) => {
        return apiResponse.body.raw as T;
      })
    );
  }

  /**
   * Update a existing group.
   * @param publicID ID of the selected group.
   * @param group Data of the new group.
   */
  public putGroup(publicID: number, group: T): Observable<T> {
    const options = this.post;
    options.params = new HttpParams();
    return this.api.callPut<T>(`${ this.servicePrefix }/${ publicID }`, group, options).pipe(
      map((apiResponse: HttpResponse<APIUpdateSingleResponse<T>>) => {
        return apiResponse.body.result as T;
      })
    );
  }

  /**
   * Delete a existing group.
   * @param publicID
   * @param action
   * @param groupID
   */
  public deleteGroup(publicID: number, action: string = null, groupID?: number): Observable<T> {
    const groupDeleteOptions: any = this.post;
    let params = new HttpParams();
    params = params.append('action', action);
    if (groupID) {
      params = params.append('group_id', JSON.stringify(groupID));
    }

    groupDeleteOptions.params = params;

    return this.api.callDelete<T>(`${ this.servicePrefix }/${ publicID }`, groupDeleteOptions).pipe(
      map((apiResponse) => {
        return apiResponse.body;
      })
    );
  }

  /**
   * Get the number of groups.
   */
  public countGroups(filter?: any): Observable<number> {
    const options = this.post;
    let httpParams: HttpParams = new HttpParams();
    if (filter !== undefined) {
      httpParams = httpParams.set('filter', JSON.stringify(filter));
    }
    options.params = httpParams;
    return this.api.callHead<T>(`${ this.servicePrefix }/`, options).pipe(
      map((apiResponse: HttpResponse<APIGetMultiResponse<T>>) => {
        return +apiResponse.headers.get('X-Total-Count');
      })
    );
  }


}
