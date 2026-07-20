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
import { CollectionParameters } from 'src/app/services/models/api-parameter';
import { APIGetMultiResponse } from 'src/app/services/models/api-response';

@Injectable({ providedIn: 'root' })
export class RiskAssesmentsReportService extends BaseApiService<any> {
  public servicePrefix = 'isms/reports/risk_assessments';

  constructor(protected api: ApiCallService) {
    super(api);
  }

  /**
   * Get a paginated Risk Assessments report.
   * Pass `limit: 0` to retrieve the full result set (used for exports).
   */
  getRiskAssesmentsReportList(params: CollectionParameters): Observable<APIGetMultiResponse<any>> {
    const httpParams = this.buildHttpParams(params);
    return this.handleGetRequest<APIGetMultiResponse<any>>(this.servicePrefix, httpParams);
  }

}
