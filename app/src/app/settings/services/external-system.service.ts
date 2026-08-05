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
import { ApiCallService } from '../../services/api-call.service';
import { map } from 'rxjs/operators';

@Injectable({
  providedIn: 'root'
})
export class ExternalSystemService {

  private servicePrefix: string = 'externalsystem';

  constructor(private api: ApiCallService) {
  }

  public getExternSystemList() {
    return this.api.callGet<any[]>(this.servicePrefix + '/').pipe(
      map((apiResponse) => {
        if (apiResponse.status === 204) {
          return [];
        }
        return apiResponse.body;
      })
    );
  }

  public getExternSystemParams(name: string) {
    return this.api.callGet<any>(this.servicePrefix + '/parameters/' + name).pipe(
      map((apiResponse) => {
        if (apiResponse.status === 204) {
          return [];
        }
        return apiResponse.body;
      })
    );
  }

  public getExternSystemVariables(name: string) {
    return this.api.callGet<any>(this.servicePrefix + '/variables/' + name).pipe(
      map((apiResponse) => {
        if (apiResponse.status === 204) {
          return [];
        }
        return apiResponse.body;
      })
    );
  }
}
