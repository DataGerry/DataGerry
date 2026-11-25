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
import { EMPTY, Observable, catchError, filter, from, map } from 'rxjs';

import { CoreConfirmationModalComponent } from 'src/app/core/components/dialog/confirmation/core-confirmation-modal.component';
import { FullscreenModalService } from 'src/app/core/services/fullscreen-modal.service';
import { BlockedPersonRow, SyncConfirmation } from '../models/person-sync';
import { BLOCKED_COPY_RESULT, PersonSyncBlockedModalComponent } from './modals/person-sync-blocked-modal.component';
/* ------------------------------------------------------------------------------------------------------------------ */

const MODAL_OPTIONS = {
    size: 'lg' as const,
    windowClass: 'dg-modal-window',
    backdropClass: 'dg-modal-window-backdrop'
};


/** The confirmations of the person sync screens. Each emits once, and only when the user confirms. */
@Injectable({ providedIn: 'root' })
export class PersonSyncDialogService {

    private readonly modalService = inject(NgbModal);
    private readonly fullscreenModal = inject(FullscreenModalService);

/* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    public confirm(confirmation: SyncConfirmation): Observable<void> {
        const modal = this.modalService.open(
            CoreConfirmationModalComponent,
            this.fullscreenModal.withFullscreenContainer(MODAL_OPTIONS)
        );

        modal.componentInstance.title = confirmation.title;
        modal.componentInstance.message = confirmation.message;
        modal.componentInstance.confirmButtonText = confirmation.confirmLabel;
        modal.componentInstance.confirmTone = confirmation.confirmTone ?? 'brand';
        modal.componentInstance.warningMessage = confirmation.warningMessage ?? '';

        return this.onResult(modal.result, 'confirmed');
    }


    /** Lists the persons that cannot move to their new Type; emits when the user picks Copy. */
    public confirmCopyBlocked(rows: BlockedPersonRow[]): Observable<void> {
        const modal = this.modalService.open(
            PersonSyncBlockedModalComponent,
            this.fullscreenModal.withFullscreenContainer(MODAL_OPTIONS)
        );

        (modal.componentInstance as PersonSyncBlockedModalComponent).rows.set(rows);

        return this.onResult(modal.result, BLOCKED_COPY_RESULT);
    }

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    private onResult(result: Promise<unknown>, expected: string): Observable<void> {
        return from(result).pipe(
            catchError(() => EMPTY),
            filter(value => value === expected),
            map(() => undefined)
        );
    }
}
