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
import { Injectable, Type, inject } from '@angular/core';
import { NgbModal } from '@ng-bootstrap/ng-bootstrap';

import { EMPTY, Observable, from } from 'rxjs';
import { catchError, filter, map } from 'rxjs/operators';

import { CoreConfirmationModalComponent } from 'src/app/core/components/dialog/confirmation/core-confirmation-modal.component';
import { FullscreenModalService } from 'src/app/core/services/fullscreen-modal.service';

import { ConnectionFormModalComponent } from '../components/connection-form-modal/connection-form-modal.component';
import { InterfaceLinksModalComponent } from '../components/interface-links-modal/interface-links-modal.component';
import { PortBulkDeleteModalComponent } from '../components/port-bulk-delete-modal/port-bulk-delete-modal.component';
import { PortBulkEditModalComponent } from '../components/port-bulk-edit-modal/port-bulk-edit-modal.component';
import { PortCreateWizardModalComponent } from '../components/port-create-wizard-modal/port-create-wizard-modal.component';
import { PortFormModalComponent } from '../components/port-form-modal/port-form-modal.component';
import { CmdbPortConnection } from '../models/port-connection.types';
import { CmdbPort, PortSelection } from '../models/ports-overview.types';
/* ------------------------------------------------------------------------------------------------------------------ */

/**
 * Opens the dialogs of the ports section.
 *
 * Every one of them reports the same way: the returned observable emits once, when something was
 * stored, and completes without emitting when the user cancelled. That is what a caller reloads on.
 */
@Injectable({ providedIn: 'root' })
export class PortDialogService {

    private readonly modalService = inject(NgbModal);
    private readonly fullscreenModal = inject(FullscreenModalService);

/* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    /** One port, created or edited by hand. */
    public openPortForm(objectId: number, objectLabel: string, port: CmdbPort | null): Observable<void> {
        return this.open(PortFormModalComponent, (instance) => {
            instance.objectId = objectId;
            instance.objectLabel = objectLabel;
            instance.port = port;
        });
    }


    /** The creation assistant: a whole device's ports, named and previewed server-side. */
    public openCreateWizard(objectId: number, objectLabel: string): Observable<void> {
        return this.open(PortCreateWizardModalComponent, (instance) => {
            instance.objectId = objectId;
            instance.objectLabel = objectLabel;
        });
    }


    /** Cables a port, or edits the cable of the connection it already holds. */
    public openConnectionForm(
        port: CmdbPort,
        objectLabel: string,
        connection: CmdbPortConnection | null
    ): Observable<void> {
        return this.open(ConnectionFormModalComponent, (instance) => {
            instance.port = port;
            instance.objectLabel = objectLabel;
            instance.connection = connection;
        });
    }


    /** Writes the same status, type, speed or description onto every selected port. */
    public openBulkEdit(objectId: number, objectLabel: string, ports: readonly PortSelection[]): Observable<void> {
        return this.open(PortBulkEditModalComponent, (instance) => {
            instance.objectId = objectId;
            instance.objectLabel = objectLabel;
            instance.ports = ports;
        });
    }


    /** Deletes the selected ports, after showing what the delete takes with them. */
    public openBulkDelete(objectId: number, objectLabel: string, ports: readonly PortSelection[]): Observable<void> {
        return this.open(PortBulkDeleteModalComponent, (instance) => {
            instance.objectId = objectId;
            instance.objectLabel = objectLabel;
            instance.ports = ports;
        });
    }


    /**
     * Asks before cutting the cables of several ports at once.
     *
     * Deliberately not the delete dialog: no port is removed, and that wording is what makes a user
     * fear for the ports themselves. Emits once the user confirmed.
     */
    public confirmBulkDisconnect(portCount: number, connectionCount: number): Observable<void> {
        const modal = this.modalService.open(CoreConfirmationModalComponent, this.fullscreenModal.withFullscreenContainer({
            size: 'lg',
            windowClass: 'dg-modal-window',
            backdropClass: 'dg-modal-window-backdrop'
        }));

        modal.componentInstance.title = 'Disconnect ports';
        modal.componentInstance.message =
            `Do you want to disconnect ${ portCount } selected ports? `
            + `That cuts ${ connectionCount } connection(s).`;
        modal.componentInstance.confirmButtonText = 'Disconnect';
        modal.componentInstance.confirmButtonClass = 'btn-danger';
        modal.componentInstance.warningMessage =
            'The cable information is removed with each connection. Every port stays.';

        return from(modal.result as Promise<string>).pipe(
            catchError(() => EMPTY),
            filter((result) => result === 'confirmed'),
            map(() => undefined)
        );
    }


    /**
     * The interface rows one port carries.
     *
     * Reading is its own right, so the dialog opens without write rights too - it then lists what the
     * port is attached to and offers nothing else.
     */
    public openInterfaceLinks(
        port: CmdbPort,
        objectLabel: string,
        rights: { canEdit: boolean; canDelete: boolean }
    ): Observable<void> {
        return this.open(InterfaceLinksModalComponent, (instance) => {
            instance.port = port;
            instance.objectLabel = objectLabel;
            instance.canEdit = rights.canEdit;
            instance.canDelete = rights.canDelete;
        }, 'xl');
    }

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    /** Hosted inside the fullscreen element while one is open; a body-level modal is not painted there. */
    private open<T>(component: Type<T>, prefill: (instance: T) => void, size: 'lg' | 'xl' = 'lg'): Observable<void> {
        const modal = this.modalService.open(component, this.fullscreenModal.withFullscreenContainer({
            size,
            windowClass: 'dg-modal-window',
            backdropClass: 'dg-modal-window-backdrop'
        }));

        prefill(modal.componentInstance as T);

        return from(modal.result as Promise<boolean>).pipe(
            // Dismissing rejects the promise; cancelling is not an error.
            catchError(() => EMPTY),
            filter((stored) => stored === true),
            map(() => undefined)
        );
    }
}
