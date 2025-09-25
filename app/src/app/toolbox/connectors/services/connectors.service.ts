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

* You should have received a copy of the GNU Affero General Public License
* along with this program. If not, see <https://www.gnu.org/licenses/>.
*/
import { Injectable } from '@angular/core';
import { HttpHeaders, HttpResponse } from '@angular/common/http';
import { Observable } from 'rxjs';
import { catchError, map } from 'rxjs/operators';

import { ApiCallService, ApiServicePrefix, resp } from 'src/app/services/api-call.service';

@Injectable({
  providedIn: 'root'
})
export class ConnectorsService implements ApiServicePrefix {
  public servicePrefix: string = 'open_celium';

  public options = {
    headers: new HttpHeaders({ 'Content-Type': 'application/json' }),
    params: {},
    observe: resp
  };

  constructor(private api: ApiCallService) { }

  /**
   * Get all connectors from OpenCelium
   */
  public getAllConnectors(): Observable<any> {
    const options = { ...this.options };
    return this.api.callGet<any>(`${this.servicePrefix}/connectors`, options)
      .pipe(
        map((res: HttpResponse<any>) => res.body),
        catchError((error) => {
          throw error;
        })
      );
  }

  /**
   * Get all invokers from OpenCelium
   */
  public getAllInvokers(): Observable<any> {
    const options = { ...this.options };
    return this.api.callGet<any>(`${this.servicePrefix}/invokers`, options)
      .pipe(
        map((res: HttpResponse<any>) => res.body),
        catchError((error) => {
          throw error;
        })
      );
  }

  /**
   * Test connector credentials
   */
  public testConnectorCredentials(connectorData: any): Observable<any> {
    const options = { ...this.options };
    return this.api.callPost<any>(`${this.servicePrefix}/connectors/check`, connectorData, options)
      .pipe(
        map((res: HttpResponse<any>) => res.body),
        catchError((error) => {
          throw error;
        })
      );
  }

  /**
   * Create a new connector
   */
  public createConnector(connectorData: any): Observable<any> {
    const options = { ...this.options };
    return this.api.callPost<any>(`${this.servicePrefix}/connectors`, connectorData, options)
      .pipe(
        map((res: HttpResponse<any>) => res.body),
        catchError((error) => {
          throw error;
        })
      );
  }

  /**
   * Update an existing connector
   */
  public updateConnector(connectorId: number, connectorData: any): Observable<any> {
    const options = { ...this.options };
    const payload = { ...connectorData, connectorId };
    return this.api.callPut<any>(`${this.servicePrefix}/connectors/${connectorId}`, payload, options)
      .pipe(
        map((res: HttpResponse<any>) => res.body),
        catchError((error) => {
          throw error;
        })
      );
  }

  /**
   * Delete a connector
   */
  public deleteConnector(connectorId: number): Observable<any> {
    const options = { ...this.options };
    return this.api.callDelete<any>(`${this.servicePrefix}/connectors/${connectorId}`, options)
      .pipe(
        map((res: HttpResponse<any>) => res.body),
        catchError((error) => {
          throw error;
        })
      );
  }
}
