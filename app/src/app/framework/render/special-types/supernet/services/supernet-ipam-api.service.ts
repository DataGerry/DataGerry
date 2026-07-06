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
import { HttpHeaders } from '@angular/common/http';
import { Observable } from 'rxjs';
import { map } from 'rxjs/operators';

import { ApiCallService, resp } from '../../../../../services/api-call.service';
import {
    SupernetValidationRequest,
    SupernetValidationResponse
} from '../models/supernet-validation.types';
/* ------------------------------------------------------------------------------------------------------------------ */


@Injectable({ providedIn: 'root' })
export class SupernetIpamApiService {

    public servicePrefix: string = 'ipam/validate';

    private readonly api = inject(ApiCallService);

    private readonly options = {
        headers: new HttpHeaders({ 'Content-Type': 'application/json' }),
        params: {},
        observe: resp
    };

/* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    public validateSupernet(payload: SupernetValidationRequest): Observable<SupernetValidationResponse> {
        return this.api.callPost<SupernetValidationResponse>(this.servicePrefix + '/supernet', payload, this.options).pipe(
            map(response => response?.body as SupernetValidationResponse)
        );
    }
}
