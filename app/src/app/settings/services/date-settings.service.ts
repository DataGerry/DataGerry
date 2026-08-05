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
import { HttpParams } from '@angular/common/http';

import { Observable } from 'rxjs';
import { map } from 'rxjs/operators';

import { ApiCallService, ApiServicePrefix, httpObserveOptions } from '../../services/api-call.service';
/* ------------------------------------------------------------------------------------------------------------------ */


@Injectable({
  providedIn: 'root'
})
export class DateSettingsService<T = any> implements ApiServicePrefix {

  public readonly servicePrefix: string = 'date';
  /**
   * The current date settings.
   */
  public currentDateSettings$: any;

  constructor(private api: ApiCallService) {
    this.getDateSettings().subscribe(() => {});
  }

  public get currentDateSettings() {
    return this.currentDateSettings$;
  }

  public set currentDateSettings(value: any) {
    this.currentDateSettings$ = value;
  }

  public getDateSettings(): Observable<T> {
    return this.api.callGet<T>(`${this.servicePrefix}/`).pipe(
      map((apiResponse) => {
        this.currentDateSettings = apiResponse.body;
        return apiResponse.body;
      })
    );
  }

  public postDateSettings(data: T): Observable<T> {
    const options = httpObserveOptions;
    options.params = new HttpParams();
    return this.api.callPost<T>(`${ this.servicePrefix }/`, data, options).pipe(
      map((apiResponse) => {
        this.currentDateSettings = apiResponse.body;
        return apiResponse.body;
      })
    );
  }
}
