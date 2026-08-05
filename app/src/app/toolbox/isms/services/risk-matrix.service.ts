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
import { IsmsRiskMatrix } from '../models/risk-matrix.model';
import {
  APIUpdateSingleResponse
} from 'src/app/services/models/api-response';

@Injectable({
  providedIn: 'root'
})
export class RiskMatrixService<T = any> implements ApiServicePrefix {
  public servicePrefix: string = 'isms/risk_matrix';

  public options = {
    headers: new HttpHeaders({ 'Content-Type': 'application/json' }),
    params: {},
    observe: resp
  };

  constructor(private api: ApiCallService) { }

  /**
   * Fetch the single RiskMatrix record (we assume only one).
   */
  public getRiskMatrix(publicId: number): Observable<IsmsRiskMatrix> {
    const options = { ...this.options };
    return this.api.callGet<IsmsRiskMatrix>(`${this.servicePrefix}/${publicId}`, options)
      .pipe(
        map((res: HttpResponse<IsmsRiskMatrix>) => res.body),
        catchError((error) => {
          throw error;
        })
      );
  }


  /**
   * Update the single RiskMatrix record.
   */
  public updateRiskMatrix(data: IsmsRiskMatrix): Observable<APIUpdateSingleResponse<T>> {
    const options = { ...this.options };
    // If there's a known public_id, use it; otherwise assume "1"
    const matrixId = data.public_id || 1;
    return this.api.callPut<APIUpdateSingleResponse<T>>(`${this.servicePrefix}/${matrixId}`, data, options)
      .pipe(
        map((res: HttpResponse<APIUpdateSingleResponse<T>>) => res.body),
        catchError((error) => {
          throw error;
        })
      );
  }
}
