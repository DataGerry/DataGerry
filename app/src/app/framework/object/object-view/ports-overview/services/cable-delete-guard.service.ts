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

import { NgbModal } from '@ng-bootstrap/ng-bootstrap';

import { Observable, defer, forkJoin, of } from 'rxjs';
import { catchError, finalize, map, switchMap } from 'rxjs/operators';

import { CoreWarningModalComponent } from 'src/app/core/components/dialog/core-warning-modal/core-warning-modal.component';
import { FullscreenModalService } from 'src/app/core/services/fullscreen-modal.service';
import { LoaderService } from 'src/app/core/services/loader.service';
import { RenderResult } from 'src/app/framework/models/cmdb-render';
import { SpecialType } from 'src/app/framework/models/special-type';

import { CableUsage } from '../models/port-connection.types';
import { objectDisplayLabel } from '../utils/object-label.util';
import { describeEndpoint } from '../utils/port-connection.util';
import { ConnectionEndpointService } from './connection-endpoint.service';
import { PortConnectionService } from './port-connection.service';
/* ------------------------------------------------------------------------------------------------------------------ */

/**
 * Keeps a cable CI that a connection still holds out of the delete dialogs.
 *
 * Only a CABLE object is prechecked, and a precheck that cannot be read lets the delete through: the
 * delete route stays the authority, so an unreadable connection never makes a cable undeletable.
 */
@Injectable({ providedIn: 'root' })
export class CableDeleteGuardService {

    private readonly connectionService = inject(PortConnectionService);
    private readonly endpointService = inject(ConnectionEndpointService);
    private readonly fullscreenModalService = inject(FullscreenModalService);
    private readonly loaderService = inject(LoaderService);
    private readonly modalService = inject(NgbModal);

/* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    /**
     * Whether one object may go on to its delete dialog. Says where to disconnect it when it may not.
     *
     * A bulk delete is deliberately not prechecked: the delete route refuses a whole selection in one
     * query, naming every blocked cable, which a per-object precheck could only repeat one request at
     * a time.
     */
    public ensureDeletable(result: RenderResult): Observable<boolean> {
        const cableId = this.cableIdOf(result);

        if (cableId == null) {
            return of(true);
        }

        return this.readUsage(cableId).pipe(
            switchMap((usage) => usage?.in_use ? this.blockSingle(result, usage) : of(true))
        );
    }

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    private cableIdOf(result: RenderResult): number | null {
        if (result?.object_information?.special_type !== SpecialType.CABLE) {
            return null;
        }

        return result?.object_information?.object_id ?? null;
    }


    private readUsage(cableId: number): Observable<CableUsage | null> {
        // Deferred, so the loader is only shown once someone actually waits for the answer.
        return defer(() => {
            this.loaderService.show();

            return this.connectionService.getCableUsage(cableId);
        }).pipe(
            catchError(() => of(null)),
            finalize(() => this.loaderService.hide())
        );
    }


    /** Names both ends of the connection, so the user knows where to disconnect the cable. */
    private blockSingle(result: RenderResult, usage: CableUsage): Observable<boolean> {
        return this.readEndpointLabels(usage.endpoints).pipe(
            map((endpoints) => {
                const connection = endpoints.length === 2
                    ? `the connection between ${ endpoints[0] } and ${ endpoints[1] }`
                    : `connection #${ usage.connection_id }`;

                this.openInUseModal(
                    'Cable is still in use',
                    `${ objectDisplayLabel(result) } cannot be deleted while it is used by ${ connection }. `
                        + 'Disconnect it first, then delete the cable.'
                );

                return false;
            })
        );
    }


    /** Best effort: an end that cannot be read falls back to the connection id in the message. */
    private readEndpointLabels(endpoints: number[] | null): Observable<string[]> {
        const portIds = endpoints ?? [];

        if (portIds.length !== 2) {
            return of([]);
        }

        return defer(() => {
            this.loaderService.show();

            return forkJoin(portIds.map((portId) => this.endpointService.endpointOf(portId)));
        }).pipe(
            map((resolved) => resolved.map((endpoint) => describeEndpoint(endpoint) ?? `Port #${ endpoint.portId }`)),
            catchError(() => of<string[]>([])),
            finalize(() => this.loaderService.hide())
        );
    }


    private openInUseModal(title: string, message: string): void {
        const modalRef = this.modalService.open(
            CoreWarningModalComponent,
            this.fullscreenModalService.withFullscreenContainer({
                centered: true,
                windowClass: 'dg-modal-window',
                backdropClass: 'dg-modal-window-backdrop'
            })
        );

        modalRef.componentInstance.title = title;
        modalRef.componentInstance.message = message;
    }
}
