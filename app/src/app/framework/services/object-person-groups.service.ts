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
* along with this program. If not, see <https://www.gnu.org/licenses/>.
*/
import { Injectable, inject } from '@angular/core';
import { HttpHeaders, HttpResponse } from '@angular/common/http';
import { Observable, map } from 'rxjs';

import { ApiCallService, resp } from '../../services/api-call.service';
import {
    PersonGroupsAnswer,
    PersonGroupsBody,
    PersonGroupsChange,
    PersonSelection
} from '../models/person-selector';
/* ------------------------------------------------------------------------------------------------------------------ */

/** The person groups a person belongs to, read and changed from the person's side. */
@Injectable({ providedIn: 'root' })
export class ObjectPersonGroupsService {

    private readonly api = inject(ApiCallService);

    private readonly options = {
        headers: new HttpHeaders({ 'Content-Type': 'application/json' }),
        observe: resp
    };

/* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    /** Only the groups the caller may read are listed. */
    public getPersonGroups(personId: number): Observable<PersonSelection[]> {
        return this.api.callGet<PersonGroupsBody>(`objects/${ personId }/person_groups`, this.options)
            .pipe(map((response: HttpResponse<PersonGroupsBody>) => this.toAnswer(response.body).results));
    }


    /** All or none; answers the person's groups afterwards. */
    public changePersonGroups(personId: number, change: PersonGroupsChange): Observable<PersonGroupsAnswer> {
        return this.api.callPatch<PersonGroupsBody>(`objects/${ personId }/person_groups`, change, this.options)
            .pipe(map((response: HttpResponse<PersonGroupsBody>) => this.toAnswer(response.body)));
    }

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    /** The backend answers the groups as a bare list; a wrapped answer is read too. */
    private toAnswer(body: PersonGroupsBody): PersonGroupsAnswer {
        if (Array.isArray(body)) {
            return { results: body, failed: [] };
        }

        return { results: body?.results ?? [], failed: body?.failed ?? [] };
    }
}
