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
import { HttpHeaders } from '@angular/common/http';

import { Observable } from 'rxjs';
import { map } from 'rxjs/operators';

import { ApiCallService, ApiServicePrefix, resp } from '../../services/api-call.service';

import { CmdbDao } from '../models/cmdb-dao';
/* ------------------------------------------------------------------------------------------------------------------ */

export const httpObserveOptions = {
  headers: new HttpHeaders({
    'Content-Type': 'application/json'
  }),
  observe: resp
};

export const PARAMETER = 'params';
export const COOKIE_NAME = 'onlyActiveObjCookie';

@Injectable({
  providedIn: 'root'
})
export class SpecialService<T = CmdbDao> implements ApiServicePrefix {
  public servicePrefix: string = 'special';

  constructor(private api: ApiCallService) { }


  /**
   * Constructs the full route ensuring no double or triple slashes.
   * @param endpoint The API endpoint path.
   * @returns The full route string.
   */
  private constructRoute(endpoint: string): string {
    // Remove leading slash if present
    endpoint = endpoint.startsWith('/') ? endpoint.slice(1) : endpoint;
    return `${this.servicePrefix}/${endpoint}`;
  }

  /* ------------------------------------------------------------------------------------------------------------------ */
  /*                                                     API SECTION                                                    */
  /* ------------------------------------------------------------------------------------------------------------------ */

  /**
   * Requests steps for intro and info about data in DB
   * 
   * @returns Steps for intro and if there are any categories, types, and objects in the database
   */
  public getIntroStarter(): Observable<T[]> {
    // Create a local copy of httpObserveOptions to avoid mutating the global object
    const options = {
      ...httpObserveOptions,
      [PARAMETER]: { onlyActiveObjCookie: this.api.readCookies(COOKIE_NAME) }
    };

    const route = this.constructRoute('intro');

    return this.api.callGet<T[]>(route, options).pipe(
      map(apiResponse => apiResponse.body)
    );
  }


  /**
   * Sends selected profiles of assistant to backend which should be created
   * 
   * @param data string of profiles separated by '#'
   * @returns created public_ids of types
   */
  public createProfiles(data: string): Observable<T[]> {
    // Create a local copy of httpObserveOptions to avoid mutating the global object
    const options = {
      ...httpObserveOptions,
      [PARAMETER]: { data }
    };

    const route = this.constructRoute('profiles');

    return this.api.callPost<T>(route, JSON.stringify(data), options).pipe(
      map(apiResponse => apiResponse.body)
    );
  }
}
