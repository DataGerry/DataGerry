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
import { NgbModal } from '@ng-bootstrap/ng-bootstrap';

import { LocationTreePickerModalComponent } from './location-tree-picker-modal.component';
import { LocationSelection } from './location-tree-select.model';
/* ------------------------------------------------------------------------------------------------------------------ */

export interface LocationPickerOptions {
    /** public_id of the currently selected location (highlighted in the tree). */
    selectedId: number | null;
    /** public_id of the edited object, so its own node and descendants stay unselectable. */
    excludeObjectId: number | null;
    title?: string;
}

/**
 * Opens the location tree picker modal and resolves with the chosen location, or null when the
 * modal is dismissed without a selection.
 */
@Injectable({ providedIn: 'root' })
export class LocationPickerService {

    private readonly modalService = inject(NgbModal);

    public open(options: LocationPickerOptions): Promise<LocationSelection | null> {
        const modalRef = this.modalService.open(LocationTreePickerModalComponent, {
            size: 'lg',
            centered: true,
            windowClass: 'dg-modal-window',
            backdropClass: 'dg-modal-window-backdrop'
        });

        modalRef.componentInstance.selectedId = options.selectedId;
        modalRef.componentInstance.excludeObjectId = options.excludeObjectId;

        if (options.title) {
            modalRef.componentInstance.title = options.title;
        }

        return modalRef.result.then(
            (selection: LocationSelection) => selection ?? null,
            () => null
        );
    }
}
