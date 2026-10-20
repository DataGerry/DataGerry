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
import { HttpHeaders, HttpParams, HttpResponse } from '@angular/common/http';

import { Observable } from 'rxjs';
import { map } from 'rxjs/operators';

import { ApiCallService, resp } from 'src/app/services/api-call.service';
import { CablingResponse } from '../models/cabling.types';
/* ------------------------------------------------------------------------------------------------------------------ */

/** The two reads of the cabling view: an object's whole ring, and what one port leads to. */
@Injectable({ providedIn: 'root' })
export class CablingService {

    public readonly servicePrefix = 'ports';

    private readonly api = inject(ApiCallService);
    private readonly jsonHeaders = new HttpHeaders({ 'Content-Type': 'application/json' });

/* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    /** The object, every object one of its cables reaches, and the cables between them. */
    public getObjectCabling(objectId: number): Observable<CablingResponse> {
        return this.read(`${ this.servicePrefix }/object/${ objectId }/cabling`, objectId);
    }


    /** The one object at the far end of this port's cable. A free port answers with no node. */
    public getPortCabling(portId: number): Observable<CablingResponse> {
        return this.read(`${ this.servicePrefix }/${ portId }/cabling`, null);
    }

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    private read(route: string, focalObjectId: number | null): Observable<CablingResponse> {
        const options = { headers: this.jsonHeaders, params: new HttpParams(), observe: resp };

        return this.api.callGet<CablingResponse>(route, options).pipe(
            map((response: HttpResponse<CablingResponse>) => ({
                focal_object_id: response?.body?.focal_object_id ?? focalObjectId,
                nodes: response?.body?.nodes ?? [],
                edges: response?.body?.edges ?? []
            }))
        );
    }
}
