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


import { RiskClass } from '../models/risk-class.model';
import { ApiServicePrefix, resp, ApiCallService } from 'src/app/services/api-call.service';
import { CollectionParameters } from 'src/app/services/models/api-parameter';
import { APIGetMultiResponse, APIGetSingleResponse, APIInsertSingleResponse, APIUpdateSingleResponse, APIDeleteSingleResponse } from 'src/app/services/models/api-response';


@Injectable({
  providedIn: 'root'
})
export class RiskClassService<T = any> implements ApiServicePrefix {
  public servicePrefix: string = 'isms/risk_classes';

  public options = {
    headers: new HttpHeaders({
      'Content-Type': 'application/json'
    }),
    params: {},
    observe: resp
  };

  constructor(
    private api: ApiCallService) { }

  /**
   * Fetch a paginated list of Risk Classes.
   */
  public getRiskClasses(params: CollectionParameters = {
    filter: '',
    limit: 10,
    order: 1,
    sort: 'sort',
    page: 1,
  }): Observable<APIGetMultiResponse<RiskClass>> {
    const options = this.options;
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

    return this.api.callGet<APIGetMultiResponse<RiskClass>>(`${this.servicePrefix}/`, options).pipe(
      map((apiResponse: HttpResponse<APIGetMultiResponse<RiskClass>>) => apiResponse.body),
      catchError((error) => {
        throw error;
      })
    );
  }


  /**
   * Fetch a single Risk Class by its public ID.
   */
  public getRiskClassById(publicId: number): Observable<APIGetSingleResponse<T>> {
    const options = { ...this.options };
    options.params = new HttpParams();

    return this.api.callGet<APIGetSingleResponse<T>>(`${this.servicePrefix}/${publicId}`, options)
      .pipe(
        map((apiResponse: HttpResponse<APIGetSingleResponse<T>>) => apiResponse.body),
        catchError((error) => {
          throw error;
        })
      );
  }


  /**
   * Create a new Risk Class.
   */
  public createRiskClass(riskClassData: Partial<RiskClass>): Observable<APIInsertSingleResponse<T>> {
    const options = { ...this.options };


    let httpParams = new HttpParams();
    for (const key in riskClassData) {
      const val = typeof riskClassData[key] === 'object'
        ? JSON.stringify(riskClassData[key])
        : String(riskClassData[key]);
      httpParams = httpParams.set(key, val);
    }
    options.params = httpParams;

    return this.api.callPost<APIInsertSingleResponse<T>>(`${this.servicePrefix}/`, riskClassData, options)
      .pipe(
        map((apiResponse: HttpResponse<APIInsertSingleResponse<T>>) => apiResponse.body),
        catchError((error) => {
          throw error;
        })
      );
  }


  /**
   * Update an existing Risk Class by its public ID.
   */
  public updateRiskClass(
    publicId: number,
    riskClassData: Partial<RiskClass>
  ): Observable<APIUpdateSingleResponse<T>> {
    // Copy the existing options object
    const options = { ...this.options };

    let httpParams = new HttpParams();
    options.params = httpParams;

    // Build the request body: combine the provided data with public_id
    const body = {
      public_id: publicId,
      ...riskClassData
    };

    return this.api.callPut<APIUpdateSingleResponse<T>>(
      `${this.servicePrefix}/${publicId}`,
      body,
      options
    ).pipe(
      map((apiResponse: HttpResponse<APIUpdateSingleResponse<T>>) => apiResponse.body),
      catchError((error) => {
        throw error;
      })
    );
  }


  public updateRiskClassOrder(
    riskClassData: Partial<Array<RiskClass>>
  ): Observable<APIUpdateSingleResponse<T>> {
    // Copy the existing options object
    const options = { ...this.options };

    let httpParams = new HttpParams();
    options.params = httpParams;

    // Build the request body: combine the provided data with public_id
    const body = [...riskClassData]

      ;

    return this.api.callPut<APIUpdateSingleResponse<T>>(
      `${this.servicePrefix}/multiple`,
      body,
      options
    ).pipe(
      map((apiResponse: HttpResponse<APIUpdateSingleResponse<T>>) => apiResponse.body),
      catchError((error) => {
        throw error;
      })
    );
  }



  /**
   * Delete a Risk Class by its public ID.
   */
  public deleteRiskClass(publicId: number): Observable<APIDeleteSingleResponse<T>> {
    const options = { ...this.options };
    options.params = new HttpParams();


    return this.api.callDelete<APIDeleteSingleResponse<T>>(`${this.servicePrefix}/${publicId}`, options)
      .pipe(
        map((apiResponse: HttpResponse<APIDeleteSingleResponse<T>>) => apiResponse.body),
        catchError((error) => {
          throw error;
        })
      );
  }
}
