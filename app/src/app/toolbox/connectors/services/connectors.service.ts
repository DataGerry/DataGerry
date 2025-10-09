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
import { Observable } from 'rxjs';
import { HttpParams } from '@angular/common/http';

import { ApiCallService } from 'src/app/services/api-call.service';
import { BaseApiService } from 'src/app/core/services/base-api.service';
import { Connector } from '../models/connector.model';
import { Invoker } from '../models/invoker.model';

@Injectable({ providedIn: 'root' })
export class ConnectorsService extends BaseApiService<Connector> {
  public servicePrefix = 'open_celium/connectors';

  constructor(protected api: ApiCallService) {
    super(api);
  }

  // LIST
  getConnectors(): Observable<Connector[]> {
    const params = new HttpParams();
    return this.handleGetRequest<Connector[]>(`${this.servicePrefix}`, params);
  }

  // GET SINGLE CONNECTOR
  getConnector(connectorId: number): Observable<Connector> {
    return this.handleGetRequest<Connector>(`${this.servicePrefix}/${connectorId}`);
  }

  // INVOKERS
  getInvokers(): Observable<Invoker[]> {
    return this.handleGetRequest<Invoker[]>('open_celium/invokers', new HttpParams());
  }

  // TEST CREDENTIALS
  checkConnector(payload: Connector): Observable<boolean> {
    return this.handlePostRequest<boolean>(`${this.servicePrefix}/check`, payload);
  }

  // CREATE
  createConnector(payload: Connector): Observable<Connector> {
    return this.handlePostRequest<Connector>(`${this.servicePrefix}`, payload);
  }

  // UPDATE
  updateConnector(connectorId: number, payload: Connector): Observable<Connector> {
    const body: Connector = { ...payload, connectorId };
    return this.handlePutRequest<Connector>(`${this.servicePrefix}/${connectorId}`, body);
  }

  // DELETE
  deleteConnector(connectorId: number) {
    return this.handleDeleteRequest<void>(`${this.servicePrefix}/${connectorId}`);
  }

  // PASSWORD CHECK
  checkMasterPassword(password: string): Observable<boolean> {
    return this.handlePostRequest<boolean>(`${this.servicePrefix}/pw_check`, { password });
  }
}
