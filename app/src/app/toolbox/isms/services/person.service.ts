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
import { CmdbPerson } from '../models/person.model';

@Injectable({
    providedIn: 'root'
})
export class PersonService extends BaseApiService<CmdbPerson> {
    public servicePrefix = 'persons';

    constructor(protected api: ApiCallService) {
        super(api);
    }

    getPersons(params: CollectionParameters): Observable<APIGetMultiResponse<CmdbPerson>> {
        const httpParams = this.buildHttpParams(params);
        return this.handleGetRequest<APIGetMultiResponse<CmdbPerson>>(`${this.servicePrefix}/`, httpParams);
    }

    createPerson(person: CmdbPerson): Observable<APIInsertSingleResponse<CmdbPerson>> {
        return this.handlePostRequest<APIInsertSingleResponse<CmdbPerson>>(`${this.servicePrefix}/`, person);
    }

    updatePerson(id: number, person: CmdbPerson): Observable<APIUpdateSingleResponse<CmdbPerson>> {
        return this.handlePutRequest<APIUpdateSingleResponse<CmdbPerson>>(`${this.servicePrefix}/${id}`, person);
    }

    deletePerson(id: number): Observable<APIDeleteSingleResponse<CmdbPerson>> {
        return this.handleDeleteRequest<APIDeleteSingleResponse<CmdbPerson>>(`${this.servicePrefix}/${id}`);
    }
}