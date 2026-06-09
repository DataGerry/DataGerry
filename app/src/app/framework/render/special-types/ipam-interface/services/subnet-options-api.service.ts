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
import { HttpHeaders, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { map } from 'rxjs/operators';

import { ApiCallService, resp } from '../../../../../services/api-call.service';
import { SubnetOption, SubnetOptionsResponse } from '../models/subnet-option.types';
/* ------------------------------------------------------------------------------------------------------------------ */

/**
 * Fetches the subnet options backing the dg-ipam-interface network picker, optionally narrowed
 * to a single address family so the dropdown only offers subnets matching the selected type.
 */
@Injectable({ providedIn: 'root' })
export class SubnetOptionsApiService {

    public servicePrefix: string = 'ipam/subnet';

    /** Server clamps page_size into [1, 500]; request the max so the picker holds every subnet. */
    private static readonly MAX_PAGE_SIZE = 500;

    private readonly api = inject(ApiCallService);

/* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    public getSubnetOptions(family?: string): Observable<SubnetOption[]> {
        let params = new HttpParams().set('page_size', String(SubnetOptionsApiService.MAX_PAGE_SIZE));

        if (family) {
            params = params.set('type', family);
        }

        const options = {
            headers: new HttpHeaders({ 'Content-Type': 'application/json' }),
            params,
            observe: resp
        };

        return this.api
            .callGet<SubnetOptionsResponse>(`${this.servicePrefix}/`, options)
            .pipe(map(response => (response?.body as SubnetOptionsResponse)?.rows ?? []));
    }
}
