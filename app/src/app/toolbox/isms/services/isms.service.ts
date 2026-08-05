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
import { HttpHeaders, HttpResponse } from '@angular/common/http';
import { Observable } from 'rxjs';
import { catchError, map } from 'rxjs/operators';

import { ApiCallService, ApiServicePrefix, resp } from 'src/app/services/api-call.service';

import { IsmsConfigValidation } from '../models/isms-config-validation.model';

@Injectable({
  providedIn: 'root'
})
export class ISMSService<T = any> implements ApiServicePrefix {
  public servicePrefix: string = 'isms/config/status';

  public options = {
    headers: new HttpHeaders({ 'Content-Type': 'application/json' }),
    params: {},
    observe: resp
  };

  constructor(private api: ApiCallService) { }

  /**
   * Fetch the ISMS settings Validation Status
   */
  public getIsmsValidationStatus(): Observable<IsmsConfigValidation> {
    const options = { ...this.options };
    return this.api.callGet<IsmsConfigValidation>(`${this.servicePrefix}`, options)
      .pipe(
        map((res: HttpResponse<IsmsConfigValidation>) => res.body),
        catchError((error) => {
          throw error;
        })
      );
  }
}
