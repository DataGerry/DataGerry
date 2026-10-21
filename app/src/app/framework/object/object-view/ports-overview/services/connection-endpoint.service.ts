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

import { EMPTY, Observable, of } from 'rxjs';
import { catchError, map, switchMap } from 'rxjs/operators';

import { RenderResult } from 'src/app/framework/models/cmdb-render';
import { ObjectService } from 'src/app/framework/services/object.service';

import { CmdbPortConnection, ConnectionEndpoint } from '../models/port-connection.types';
import { CmdbPort } from '../models/ports-overview.types';
import { objectDisplayLabel } from '../utils/object-label.util';
import { peerPortIdOf } from '../utils/port-connection.util';
import { portSideLabel } from '../utils/port-side.util';
import { PortService } from './port.service';
/* ------------------------------------------------------------------------------------------------------------------ */

/** Only the label is read; the object's fields and sections say nothing about its two ends. */
const LABEL_PROJECTION = {
    'object_information.object_id': 1,
    'summary_line': 1,
    'type_information': 1
};


/** Names the two ends of a connection: device first, then port, as the user recognises them. */
@Injectable({ providedIn: 'root' })
export class ConnectionEndpointService {

    private readonly portService = inject(PortService);
    private readonly objectService = inject(ObjectService);

/* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    /** The near end, built from what the caller already holds. */
    public nearEndpoint(port: CmdbPort, objectLabel: string): ConnectionEndpoint {
        return {
            portId: port.public_id,
            portName: this.portName(port.name, port.public_id),
            sideLabel: portSideLabel(port.side),
            objectId: port.object_id,
            objectLabel: objectLabel || `Object #${ port.object_id }`
        };
    }


    /**
     * The far end of a stored connection.
     *
     * A connection the near port is not part of names nothing at all.
     */
    public farEndpoint(connection: CmdbPortConnection, nearPortId: number): Observable<ConnectionEndpoint> {
        const peerPortId = peerPortIdOf(connection, nearPortId);

        return peerPortId == null ? EMPTY : this.endpointOf(peerPortId);
    }


    /**
     * One end named from its port id alone.
     *
     * Two reads, because a connection carries port ids only and the port belongs to another object.
     * Neither is required to succeed - the connection rights do not imply access to that object, so
     * an unreadable end still shows its port.
     */
    public endpointOf(portId: number): Observable<ConnectionEndpoint> {
        return this.portService.getPort(portId).pipe(
            switchMap((port) => this.readObjectLabel(port?.object_id).pipe(
                map((objectLabel) => this.toEndpoint(portId, port, objectLabel))
            )),
            catchError(() => of(this.toEndpoint(portId, null, '')))
        );
    }

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    private readObjectLabel(objectId: number | null | undefined): Observable<string> {
        if (objectId == null) {
            return of('');
        }

        return this.objectService
            .getObjects({
                filter: [{ $match: { public_id: objectId } }],
                projection: LABEL_PROJECTION,
                limit: 1,
                sort: 'public_id',
                order: 1,
                page: 1
            })
            .pipe(
                map((response) => objectDisplayLabel((response?.results ?? [])[0] as RenderResult, objectId)),
                catchError(() => of(`Object #${ objectId }`))
            );
    }


    private toEndpoint(portId: number, port: CmdbPort | null, objectLabel: string): ConnectionEndpoint {
        return {
            portId,
            portName: this.portName(port?.name, portId),
            sideLabel: portSideLabel(port?.side),
            objectId: port?.object_id ?? null,
            objectLabel: objectLabel || 'Unknown device'
        };
    }


    private portName(name: string | null | undefined, portId: number): string {
        return name?.trim() || `Port #${ portId }`;
    }
}
