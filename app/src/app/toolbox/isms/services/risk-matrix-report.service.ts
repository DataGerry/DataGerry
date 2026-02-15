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
import {  Observable } from 'rxjs';
import { ApiCallService, resp } from 'src/app/services/api-call.service';
import { BaseApiService } from 'src/app/core/services/base-api.service';
import { ReportRiskMatrix } from '../models/risk-matrix-report.model';
import { CollectionParameters } from 'src/app/services/models/api-parameter';
import { APIGetMultiResponse } from 'src/app/services/models/api-response';
import { CmdbPerson } from '../models/person.model';
import { HttpHeaders } from '@angular/common/http';

@Injectable({ providedIn: 'root' })
export class RiskMatrixReportService extends BaseApiService<ReportRiskMatrix> {

  public servicePrefix = 'isms/reports/risk_matrix';

  constructor(protected override api: ApiCallService) { super(api); }

  /**
   * Fetch the single RiskMatrix record.
   */
  getReport(): Observable<ReportRiskMatrix> {
   
    return this.handleGetRequest<ReportRiskMatrix>(`${this.servicePrefix}`);
  }
}