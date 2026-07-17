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
import { Observable } from 'rxjs';

import { ControlMeasure, ControlMeasureBulkDeleteResult } from '../models/control-measure.model';
import {
  APIGetMultiResponse,
  APIInsertSingleResponse,
  APIUpdateSingleResponse,
  APIDeleteSingleResponse
} from 'src/app/services/models/api-response';
import { CollectionParameters } from 'src/app/services/models/api-parameter';
import { ApiCallService } from 'src/app/services/api-call.service';
import { BaseApiService } from 'src/app/core/services/base-api.service';

@Injectable({
  providedIn: 'root'
})
export class ControlMeasureService extends BaseApiService<ControlMeasure> {
  public servicePrefix = 'isms/control_measures';

  constructor(protected api: ApiCallService) {
    super(api);
  }

  getControlMeasures(params: CollectionParameters): Observable<APIGetMultiResponse<ControlMeasure>> {
    const httpParams = this.buildHttpParams(params);
    return this.handleGetRequest<APIGetMultiResponse<ControlMeasure>>(`${this.servicePrefix}/`, httpParams);
  }

  createControlMeasure(cm: ControlMeasure): Observable<APIInsertSingleResponse<ControlMeasure>> {
    return this.handlePostRequest<APIInsertSingleResponse<ControlMeasure>>(`${this.servicePrefix}/`, cm);
  }

  updateControlMeasure(id: number, cm: ControlMeasure): Observable<APIUpdateSingleResponse<ControlMeasure>> {
    return this.handlePutRequest<APIUpdateSingleResponse<ControlMeasure>>(`${this.servicePrefix}/${id}`, cm);
  }

  deleteControlMeasure(id: number): Observable<APIDeleteSingleResponse<ControlMeasure>> {
    return this.handleDeleteRequest<APIDeleteSingleResponse<ControlMeasure>>(`${this.servicePrefix}/${id}`);
  }

  /**
   * Delete multiple controls at once. Controls that are still assigned to a
   * control measure assignment (CMA) are not deleted and are returned in the
   * `in_use` list of the response.
   * @param publicIds control public ids to delete
   */
  deleteControlMeasures(publicIds: number[]): Observable<ControlMeasureBulkDeleteResult> {
    return this.handleDeleteRequest<ControlMeasureBulkDeleteResult>(
      `${this.servicePrefix}/delete/${publicIds.join(',')}`
    );
  }
}