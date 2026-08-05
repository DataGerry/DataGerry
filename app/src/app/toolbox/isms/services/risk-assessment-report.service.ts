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
import { Observable } from 'rxjs';
import { ApiCallService } from 'src/app/services/api-call.service';
import { BaseApiService } from 'src/app/core/services/base-api.service';

@Injectable({ providedIn: 'root' })
export class RiskAssesmentsReportService extends BaseApiService<any> {
  public servicePrefix = 'isms/reports/risk_assessments';

  constructor(protected api: ApiCallService) {
    super(api);
  }

  /**
   * Fetch the full Risk assessments reportlist from the backend.
   */
  getRiskAssesmentsReportList(): Observable<any[]> {
    return this.handleGetRequest<any[]>(`${this.servicePrefix}`);
  }

}
