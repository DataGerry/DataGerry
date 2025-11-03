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
import { map } from 'rxjs/operators';
import { HttpParams } from '@angular/common/http';

import { ApiCallService } from 'src/app/services/api-call.service';
import { BaseApiService } from 'src/app/core/services/base-api.service';

@Injectable({ providedIn: 'root' })
export class AutomationsService extends BaseApiService<any> {
  public servicePrefix = 'open_celium';

  constructor(protected api: ApiCallService) {
    super(api);
  }

  // LIST
  getAutomations(): Observable<any[]> {
    const params = new HttpParams();
    return this.handleGetRequest<any[]>(`${this.servicePrefix}/schedulers`, params);
  }

  // INITIAL DATA
  getInitData(): Observable<{ connectors: any[], templates: any[] }> {
    return this.handleGetRequest<any>(`${this.servicePrefix}/connections/init_data`, new HttpParams()).pipe(
      map((initData) => ({
        connectors: initData.connectors || [],
        templates: initData.templates || []
      }))
    );
  }

  // CREATE
  createAutomation(payload: any): Observable<any> {
    return this.handlePostRequest<any>(`${this.servicePrefix}/schedulers`, payload);
  }

  // UPDATE
  updateAutomation(automationId: number, payload: any): Observable<any> {
    const body: any = { ...payload, automationId };
    return this.handlePutRequest<any>(`${this.servicePrefix}/schedulers/${automationId}`, body);
  }

  // DELETE
  deleteAutomation(automationId: number) {
    return this.handleDeleteRequest<void>(`${this.servicePrefix}/schedulers/${automationId}`);
  }

  // EXECUTE SCHEDULER
  executeScheduler(automationId: number){
    return this.handleGetRequest<void>(`${this.servicePrefix}/schedulers/execute/${automationId}`, new HttpParams());
  }
}
