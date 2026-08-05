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
import { Observable } from 'rxjs';
import { map } from 'rxjs/operators';
import { ApiCallService, ApiServicePrefix } from '../../services/api-call.service';
import { CmdbStatus } from '../models/cmdb-status';


@Injectable({
  providedIn: 'root'
})
export class StatusService<T = CmdbStatus> implements ApiServicePrefix {
  public servicePrefix: string = 'status';

  constructor(private api: ApiCallService) {
  }

  public getStatusList(): Observable<T[]> {
    return this.api.callGet<T[]>(`${this.servicePrefix}/`).pipe(
      map((apiResponse) => {
        return apiResponse.body;
      })
    );
  }

  public getStatus(publicID: number): Observable<T> {
    return this.api.callGet<CmdbStatus>(`${this.servicePrefix}/${publicID}`).pipe(
      map((apiResponse) => {
        return apiResponse.body;
      })
    );
  }

  public postStatus(data: CmdbStatus) {
    return this.api.callPost<CmdbStatus>(`${this.servicePrefix}/`, data).pipe(
      map((apiResponse) => {
        return apiResponse.body;
      })
    );
  }

  public putStatus(data: CmdbStatus) {
    return this.api.callPut<CmdbStatus>(`${this.servicePrefix}/`, data).pipe(
      map((apiResponse) => {
        return apiResponse.body;
      })
    );
  }

}
