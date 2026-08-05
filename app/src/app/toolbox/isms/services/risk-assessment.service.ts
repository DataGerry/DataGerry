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
import {
  APIGetMultiResponse,
  APIGetSingleResponse,
  APIInsertSingleResponse,
  APIUpdateSingleResponse,
  APIDeleteSingleResponse
} from 'src/app/services/models/api-response';
import { CollectionParameters } from 'src/app/services/models/api-parameter';
import { ApiCallService } from 'src/app/services/api-call.service';
import { BaseApiService } from 'src/app/core/services/base-api.service';
import { RiskAssessment } from '../models/risk-assessment.model';

type DuplicateRefType = 'risk' | 'object' | 'object_group';


@Injectable({
  providedIn: 'root'
})
export class RiskAssessmentService extends BaseApiService<RiskAssessment> {
  public servicePrefix = 'isms/risk_assessments';

  constructor(protected api: ApiCallService) {
    super(api);
  }

  getRiskAssessments(params: CollectionParameters): Observable<APIGetMultiResponse<RiskAssessment>> {
    const httpParams = this.buildHttpParams(params);
    return this.handleGetRequest<APIGetMultiResponse<RiskAssessment>>(`${this.servicePrefix}/`, httpParams);
  }

  getRiskAssessmentById(id: number): Observable<APIGetSingleResponse<RiskAssessment>> {
    return this.handleGetRequest<APIGetSingleResponse<RiskAssessment>>(`${this.servicePrefix}/${id}`);
  }

  createRiskAssessment(payload: RiskAssessment): Observable<APIInsertSingleResponse<RiskAssessment>> {
    return this.handlePostRequest<APIInsertSingleResponse<RiskAssessment>>(`${this.servicePrefix}/`, payload);
  }

  updateRiskAssessment(id: number, payload: RiskAssessment): Observable<APIUpdateSingleResponse<RiskAssessment>> {
    return this.handlePutRequest<APIUpdateSingleResponse<RiskAssessment>>(`${this.servicePrefix}/${id}`, payload);
  }

  deleteRiskAssessment(id: number): Observable<APIDeleteSingleResponse<RiskAssessment>> {
    return this.handleDeleteRequest<APIDeleteSingleResponse<RiskAssessment>>(`${this.servicePrefix}/${id}`);
  }

  /** Duplicate one or more risk-assessments.  
 *  `ids` – array of risk-assessment `public_id`s to duplicate (will be comma-joined)  
 *  `refType` – context path segment (`risk|object|object_group`)  
 *  `copyCma` – whether control-measure assignments should also be cloned  */
  duplicateRiskAssessments(
    targetIds: number[],
    refType: 'risk' | 'object' | 'object_group',
    copyCma = false,
    payload: any = {}
  ) {
    const idSegment = targetIds.join(',');
  
    const url = `${this.servicePrefix}/duplicate/${refType}/${idSegment}?copy_cma=${copyCma}`;
    return this.handlePostRequest(url, payload);
  }
  


}
