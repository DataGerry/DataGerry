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
import { APIInsertSingleResponse, APIUpdateSingleResponse } from 'src/app/services/models/api-response';
import {
    AssignableInterfacePage,
    AssignableInterfaceRequest,
    InterfaceLinkPayload,
    InterfaceLinkUpdatePayload,
    PortInterfaceLink
} from '../models/interface-link.types';
/* ------------------------------------------------------------------------------------------------------------------ */

/** REST access to the links between a port and the IPAM interface rows it carries. */
@Injectable({ providedIn: 'root' })
export class InterfaceLinkService {

    public readonly servicePrefix = 'ports';

    private readonly api = inject(ApiCallService);
    private readonly jsonHeaders = new HttpHeaders({ 'Content-Type': 'application/json' });

/* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    /**
     * Every interface one port is linked to, each with its live row resolved beside it.
     *
     * A port without links answers an empty array. A link whose row is gone comes back without the
     * `interface_row` key rather than as an error, so the list still renders.
     */
    public getLinksOfPort(portId: number): Observable<PortInterfaceLink[]> {
        const options = { headers: this.jsonHeaders, params: new HttpParams(), observe: resp };
        const route = `${ this.servicePrefix }/${ portId }/interface_links/`;

        return this.api.callGet<PortInterfaceLink[]>(route, options).pipe(
            map((response: HttpResponse<PortInterfaceLink[]>) => response?.body ?? [])
        );
    }


    /**
     * The interface rows this port may still be linked to, one page at a time.
     *
     * Scoped to the port's own object unless `all_objects` widens it, and rows already linked to the
     * port are left out by the route.
     */
    public getAssignableInterfaces(portId: number, request: AssignableInterfaceRequest): Observable<AssignableInterfacePage> {
        let params = new HttpParams()
            .set('page', String(request.page))
            .set('page_size', String(request.page_size));

        if (request.search) {
            params = params.set('search', request.search);
        }

        if (request.all_objects) {
            params = params.set('all_objects', 'true');
        }

        const options = { headers: this.jsonHeaders, params, observe: resp };
        const route = `${ this.servicePrefix }/${ portId }/assignable_interfaces/`;

        return this.api.callGet<AssignableInterfacePage>(route, options).pipe(
            map((response: HttpResponse<AssignableInterfacePage>) => response?.body)
        );
    }


    /** Links one interface row to the port. A row already linked to it answers 400. */
    public createLink(portId: number, payload: InterfaceLinkPayload): Observable<PortInterfaceLink> {
        const options = { headers: this.jsonHeaders, observe: resp };
        const route = `${ this.servicePrefix }/${ portId }/interface_links/`;

        return this.api.callPost<APIInsertSingleResponse<PortInterfaceLink>>(route, payload, options).pipe(
            map((response: HttpResponse<APIInsertSingleResponse<PortInterfaceLink>>) => response?.body?.raw)
        );
    }


    /**
     * Changes the relation type of one link.
     *
     * The row reference is the link's identity and cannot move, so it is sent back unchanged; a
     * payload naming a different row is refused. Re-linking is a delete plus a create.
     */
    public updateRelationType(publicId: number, payload: InterfaceLinkUpdatePayload): Observable<PortInterfaceLink> {
        const options = { headers: this.jsonHeaders, observe: resp };
        const route = `${ this.servicePrefix }/interface_links/${ publicId }`;

        return this.api.callPut<APIUpdateSingleResponse<PortInterfaceLink>>(route, payload, options).pipe(
            map((response: HttpResponse<APIUpdateSingleResponse<PortInterfaceLink>>) => response?.body?.result)
        );
    }


    /** Removes the link. Neither the port nor the interface row is touched. */
    public deleteLink(publicId: number): Observable<void> {
        const options = { headers: this.jsonHeaders, observe: resp };
        const route = `${ this.servicePrefix }/interface_links/${ publicId }`;

        return this.api.callDelete<void>(route, options).pipe(
            map(() => undefined)
        );
    }
}
