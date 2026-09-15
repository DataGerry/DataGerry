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
import {
    APIGetMultiResponse,
    APIInsertSingleResponse,
    APIUpdateSingleResponse
} from 'src/app/services/models/api-response';
import {
    CableInfoPayload,
    CableUsage,
    CmdbPortConnection,
    PortConnectionPayload,
    UnassignedCable
} from '../models/port-connection.types';
/* ------------------------------------------------------------------------------------------------------------------ */

/** One page of the unassigned-cable list. */
export interface UnassignedCableRequest {
    page: number;
    limit: number;
    search?: string;
    connectionId?: number | null;
}


/** REST access to the connections of the CmdbObject collection `framework.portConnections`. */
@Injectable({ providedIn: 'root' })
export class PortConnectionService {

    public readonly servicePrefix = 'port_connections';

    private readonly api = inject(ApiCallService);
    private readonly jsonHeaders = new HttpHeaders({ 'Content-Type': 'application/json' });

/* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    /**
     * Every connection of one object's ports in a single call.
     *
     * A panel's internal pairing appears once, not twice, although both of its ends belong to this
     * object. A port that is connected to nothing simply has no entry.
     */
    public getConnectionsOfObject(objectId: number): Observable<CmdbPortConnection[]> {
        return this.readList(`${ this.servicePrefix }/object/${ objectId }`);
    }


    /** Every connection one port takes part in: its cable and, on a panel, its internal pairing. */
    public getConnectionsOfPort(portId: number): Observable<CmdbPortConnection[]> {
        return this.readList(`${ this.servicePrefix }/port/${ portId }`);
    }


    /**
     * The cable CIs that are free to be linked, one page at a time.
     *
     * `connectionId` adds the cable of that connection to the answer, so an edit form can preselect
     * what is already linked - a cable in use is otherwise left out.
     */
    public getUnassignedCables(request: UnassignedCableRequest): Observable<APIGetMultiResponse<UnassignedCable>> {
        // Sorted explicitly, so a page scrolled to later cannot repeat or skip a cable.
        let params = new HttpParams()
            .set('page', String(request.page))
            .set('limit', String(request.limit))
            .set('sort', 'public_id')
            .set('order', '1');

        if (request.search) {
            params = params.set('search', request.search);
        }

        if (request.connectionId != null) {
            params = params.set('connection_id', String(request.connectionId));
        }

        const options = { headers: this.jsonHeaders, params, observe: resp };
        const route = `${ this.servicePrefix }/cables/unassigned/`;

        return this.api.callGet<APIGetMultiResponse<UnassignedCable>>(route, options).pipe(
            map((response: HttpResponse<APIGetMultiResponse<UnassignedCable>>) => response?.body)
        );
    }


    /**
     * Whether a connection still holds this cable CI, which is what makes the cable undeletable.
     *
     * `endpoints` names the two ports of that connection, so the caller can say where to disconnect it.
     */
    public getCableUsage(cableId: number): Observable<CableUsage> {
        const options = { headers: this.jsonHeaders, observe: resp };
        const route = `${ this.servicePrefix }/cable_usage/${ cableId }`;

        return this.api.callGet<CableUsage>(route, options).pipe(
            map((response: HttpResponse<CableUsage>) => response?.body)
        );
    }


    /** Connects two ports. A port that already holds a cable answers 400, so the caller keeps the form open. */
    public createConnection(payload: PortConnectionPayload): Observable<CmdbPortConnection> {
        const options = { headers: this.jsonHeaders, observe: resp };
        const route = `${ this.servicePrefix }/`;

        return this.api.callPost<APIInsertSingleResponse<CmdbPortConnection>>(route, payload, options).pipe(
            map((response: HttpResponse<APIInsertSingleResponse<CmdbPortConnection>>) => response?.body?.raw)
        );
    }


    /**
     * Replaces the cable information of one connection.
     *
     * Cable-only by design: what a connection joins is immutable, so a re-cable is a delete plus a
     * create. A cable key the payload omits is unset.
     */
    public updateCableInfo(publicId: number, payload: CableInfoPayload): Observable<CmdbPortConnection> {
        const options = { headers: this.jsonHeaders, observe: resp };
        const route = `${ this.servicePrefix }/${ publicId }`;

        return this.api.callPut<APIUpdateSingleResponse<CmdbPortConnection>>(route, payload, options).pipe(
            map((response: HttpResponse<APIUpdateSingleResponse<CmdbPortConnection>>) => response?.body?.result)
        );
    }


    /** Disconnects the two ports. Both of them are free for a new cable afterwards. */
    public deleteConnection(publicId: number): Observable<void> {
        const options = { headers: this.jsonHeaders, observe: resp };

        return this.api.callDelete<void>(`${ this.servicePrefix }/${ publicId }`, options).pipe(
            map(() => undefined)
        );
    }

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    /** Both list routes answer with a bare array; nothing connected is an empty one, not an error. */
    private readList(route: string): Observable<CmdbPortConnection[]> {
        const options = { headers: this.jsonHeaders, observe: resp };

        return this.api.callGet<CmdbPortConnection[]>(route, options).pipe(
            map((response: HttpResponse<CmdbPortConnection[]>) => response?.body ?? [])
        );
    }
}
