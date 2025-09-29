/*
* DATAGERRY - OpenSource Enterprise CMDB
* Copyright (C) 2025 becon GmbH
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
import { HttpHeaders, HttpResponse } from '@angular/common/http';
import { Observable } from 'rxjs';
import { catchError, map } from 'rxjs/operators';
import { ApiCallService, ApiServicePrefix, resp } from '../../services/api-call.service';
import { ToastService } from 'src/app/layout/toast/toast.service';

@Injectable({
  providedIn: 'root'
})
export class NetboxService implements ApiServicePrefix {
  public servicePrefix: string = 'netbox';

  public options = {
    headers: new HttpHeaders({
      'Content-Type': 'application/json',
    }),
    params: {},
    observe: resp,
  };

  constructor(private api: ApiCallService, private toast: ToastService) {}

  /**
   * Fetches rack elevation SVG from NetBox API
   * @param rackId The rack ID to fetch elevation for
   */
  public getRackElevation(rackId: number): Observable<string> {
    const options = {
      ...this.options,
      responseType: 'text' as const
    };

    return this.api.callGet<string>(`${this.servicePrefix}/rack-elevation/${rackId}`, options).pipe(
      map((apiResponse: HttpResponse<string>) => apiResponse.body),
      catchError((error) => {
        this.toast.error(error?.error?.message);
        throw error;
      })
    );
  }
}
