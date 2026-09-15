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
import { inject, Injectable } from '@angular/core';
import { NgbModal, NgbModalRef } from '@ng-bootstrap/ng-bootstrap';

import { LocationTreeOrganizerModalComponent } from './location-tree-organizer-modal.component';
/* ------------------------------------------------------------------------------------------------------------------ */

/**
 * Opens the location tree organizer modal, where locations can be re-parented via drag-and-drop
 * (single or multi-selected batch). Moves are persisted from inside the modal.
 */
@Injectable({ providedIn: 'root' })
export class LocationOrganizerService {

    private readonly modalService = inject(NgbModal);

    public open(): NgbModalRef {
        return this.modalService.open(LocationTreeOrganizerModalComponent, {
            centered: true,
            size: 'lg',
            windowClass: 'dg-modal-window',
            backdropClass: 'dg-modal-window-backdrop'
        });
    }
}
