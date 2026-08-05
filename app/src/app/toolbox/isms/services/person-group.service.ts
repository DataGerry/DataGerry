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
  APIInsertSingleResponse,
  APIUpdateSingleResponse,
  APIDeleteSingleResponse
} from 'src/app/services/models/api-response';
import { CollectionParameters } from 'src/app/services/models/api-parameter';
import { ApiCallService } from 'src/app/services/api-call.service';
import { BaseApiService } from 'src/app/core/services/base-api.service';
import { CmdbPersonGroup } from '../models/person-group.model';

@Injectable({
  providedIn: 'root'
})
export class PersonGroupService extends BaseApiService<CmdbPersonGroup> {
  public servicePrefix = 'person_groups';

  constructor(protected api: ApiCallService) {
    super(api);
  }

  getPersonGroups(params: CollectionParameters): Observable<APIGetMultiResponse<CmdbPersonGroup>> {
    const httpParams = this.buildHttpParams(params);
    return this.handleGetRequest<APIGetMultiResponse<CmdbPersonGroup>>(`${this.servicePrefix}/`, httpParams);
  }

  createPersonGroup(pg: CmdbPersonGroup): Observable<APIInsertSingleResponse<CmdbPersonGroup>> {
    return this.handlePostRequest<APIInsertSingleResponse<CmdbPersonGroup>>(`${this.servicePrefix}/`, pg);
  }

  updatePersonGroup(id: number, pg: CmdbPersonGroup): Observable<APIUpdateSingleResponse<CmdbPersonGroup>> {
    return this.handlePutRequest<APIUpdateSingleResponse<CmdbPersonGroup>>(`${this.servicePrefix}/${id}`, pg);
  }

  deletePersonGroup(id: number): Observable<APIDeleteSingleResponse<CmdbPersonGroup>> {
    return this.handleDeleteRequest<APIDeleteSingleResponse<CmdbPersonGroup>>(`${this.servicePrefix}/${id}`);
  }
}
