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
    APIGetSingleResponse,
    APIInsertSingleResponse,
    APIUpdateSingleResponse
} from 'src/app/services/models/api-response';
import {
    PortBulkDeletePreview,
    PortBulkDeleteResult,
    PortBulkRequest,
    PortBulkResult,
    PortBulkUpdateRequest,
    PortNamePreview,
    PortNamingRequest
} from '../models/port-bulk.types';
import { CmdbPort, PortOverviewResponse, PortPayload } from '../models/ports-overview.types';
/* ------------------------------------------------------------------------------------------------------------------ */

/** REST access to the ports of the CmdbObject collection `framework.ports`. */
@Injectable({ providedIn: 'root' })
export class PortService {

    public readonly servicePrefix = 'ports';

    private readonly api = inject(ApiCallService);
    private readonly jsonHeaders = new HttpHeaders({ 'Content-Type': 'application/json' });

/* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    /** Every port of one object, ordered by the backend. No ports is an empty array, not an error. */
    public getPortsOfObject(objectId: number): Observable<CmdbPort[]> {
        const options = { headers: this.jsonHeaders, params: new HttpParams(), observe: resp };

        return this.api.callGet<CmdbPort[]>(`${ this.servicePrefix }/object/${ objectId }`, options).pipe(
            map((response: HttpResponse<CmdbPort[]>) => response?.body ?? [])
        );
    }


    /** What the ports section lists: the device kind and its rows, already shaped for the table. */
    public getPortOverview(objectId: number): Observable<PortOverviewResponse> {
        const options = { headers: this.jsonHeaders, params: new HttpParams(), observe: resp };
        const route = `${ this.servicePrefix }/object/${ objectId }/overview`;

        return this.api.callGet<PortOverviewResponse>(route, options).pipe(
            map((response: HttpResponse<PortOverviewResponse>) =>
                response?.body ?? { device_kind: null, rows: [], total: 0 })
        );
    }


    /** One port by id. Used to name the far end of a connection, which belongs to another object. */
    public getPort(publicId: number): Observable<CmdbPort> {
        const options = { headers: this.jsonHeaders, params: new HttpParams(), observe: resp };

        return this.api.callGet<APIGetSingleResponse<CmdbPort>>(`${ this.servicePrefix }/${ publicId }`, options).pipe(
            map((response: HttpResponse<APIGetSingleResponse<CmdbPort>>) => response?.body?.result)
        );
    }


    /** Creates one port. The owner rides in the payload; a name already taken answers 400. */
    public createPort(payload: PortPayload): Observable<CmdbPort> {
        const options = { headers: this.jsonHeaders, observe: resp };

        return this.api.callPost<APIInsertSingleResponse<CmdbPort>>(`${ this.servicePrefix }/`, payload, options).pipe(
            map((response: HttpResponse<APIInsertSingleResponse<CmdbPort>>) => response?.body?.raw)
        );
    }


    /** Replaces one port. The route takes the whole port; an omitted field is stored as null. */
    public updatePort(publicId: number, payload: PortPayload): Observable<CmdbPort> {
        const options = { headers: this.jsonHeaders, observe: resp };
        const route = `${ this.servicePrefix }/${ publicId }`;

        return this.api.callPut<APIUpdateSingleResponse<CmdbPort>>(route, payload, options).pipe(
            map((response: HttpResponse<APIUpdateSingleResponse<CmdbPort>>) => response?.body?.result)
        );
    }


    /**
     * The names a bulk creation would generate, together with the collisions on each face.
     *
     * Names come from the server on purpose: the route that previews them is the route that creates
     * them, so what the user approves is what is written.
     */
    public previewPortNames(objectId: number, payload: PortNamingRequest): Observable<PortNamePreview> {
        const options = { headers: this.jsonHeaders, observe: resp };
        const route = `${ this.servicePrefix }/object/${ objectId }/name_preview`;

        return this.api.callPost<PortNamePreview>(route, payload, options).pipe(
            map((response: HttpResponse<PortNamePreview>) => response?.body)
        );
    }


    /**
     * Creates a whole device's ports in one call, and a patch panel's internal pairing with them.
     *
     * The route re-runs the preview and refuses the batch as a whole if any name collides, so nothing
     * is written half-way.
     */
    public bulkCreatePorts(objectId: number, payload: PortBulkRequest): Observable<PortBulkResult> {
        const options = { headers: this.jsonHeaders, observe: resp };
        const route = `${ this.servicePrefix }/object/${ objectId }/bulk`;

        return this.api.callPost<PortBulkResult>(route, payload, options).pipe(
            map((response: HttpResponse<PortBulkResult>) => response?.body)
        );
    }


    /**
     * Writes the same values onto several ports of one object.
     *
     * Only the four fields the route accepts can be set, and only the ones the payload names - which
     * is why `values` is built key by key rather than from a whole port.
     */
    public bulkUpdatePorts(objectId: number, payload: PortBulkUpdateRequest): Observable<void> {
        const options = { headers: this.jsonHeaders, observe: resp };
        const route = `${ this.servicePrefix }/object/${ objectId }/bulk`;

        return this.api.callPatch<void>(route, payload, options).pipe(
            map(() => undefined)
        );
    }


    /** What a bulk delete would remove, so the confirmation can name the connections and links too. */
    public previewBulkDelete(objectId: number, portIds: readonly number[]): Observable<PortBulkDeletePreview> {
        const options = { headers: this.jsonHeaders, observe: resp };
        const route = `${ this.servicePrefix }/object/${ objectId }/bulk/delete_preview`;

        return this.api.callPost<PortBulkDeletePreview>(route, { port_ids: [...portIds] }, options).pipe(
            map((response: HttpResponse<PortBulkDeletePreview>) => response?.body)
        );
    }


    /** Deletes several ports of one object. Their connections and interface links go with them. */
    public bulkDeletePorts(objectId: number, portIds: readonly number[]): Observable<PortBulkDeleteResult> {
        const options = { headers: this.jsonHeaders, body: { port_ids: [...portIds] }, observe: resp };
        const route = `${ this.servicePrefix }/object/${ objectId }/bulk`;

        return this.api.callDelete<PortBulkDeleteResult>(route, options).pipe(
            map((response: HttpResponse<PortBulkDeleteResult>) => response?.body)
        );
    }


    /** Deletes one port. Its connections and interface links go with it, server-side. */
    public deletePort(publicId: number): Observable<void> {
        const options = { headers: this.jsonHeaders, observe: resp };

        return this.api.callDelete<void>(`${ this.servicePrefix }/${ publicId }`, options).pipe(
            map(() => undefined)
        );
    }
}
