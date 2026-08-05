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
import { IpamSupernetChildrenResponse, IpamTreeResponse } from '../models/ipam-tree.types';
/* ------------------------------------------------------------------------------------------------------------------ */


@Injectable({ providedIn: 'root' })
export class IpamTreeService {

    public servicePrefix: string = 'ipam/tree';

    private readonly api = inject(ApiCallService);

    private readonly jsonHeaders = new HttpHeaders({ 'Content-Type': 'application/json' });

/* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    /**
     * Loads the top level of the IPAM tree (supernets + unassigned networks).
     */
    public getTree(): Observable<IpamTreeResponse> {
        const options = {
            headers: this.jsonHeaders,
            params: {},
            observe: resp
        };

        return this.api
            .callGet<IpamTreeResponse>(`${this.servicePrefix}/`, options)
            .pipe(map(response => response?.body as IpamTreeResponse));
    }


    /**
     * Loads the nested child subtree of a single supernet (lazy-loaded on expand).
     *
     * @param publicId public_id of the supernet to expand
     */
    public getSupernetChildren(publicId: number): Observable<IpamSupernetChildrenResponse> {
        const options = {
            headers: this.jsonHeaders,
            params: {},
            observe: resp
        };

        return this.api
            .callGet<IpamSupernetChildrenResponse>(`${this.servicePrefix}/supernets/${publicId}`, options)
            .pipe(map(response => response?.body as IpamSupernetChildrenResponse));
    }
}
