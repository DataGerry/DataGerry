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
import { Router } from '@angular/router';
import { NgbModal } from '@ng-bootstrap/ng-bootstrap';

import { DeleteModalService } from 'src/app/core/services/delete-modal.service';
import { FullscreenModalService } from 'src/app/core/services/fullscreen-modal.service';

import { RackMountModalComponent } from '../components/rack-mount-modal/rack-mount-modal.component';
import { RackArea, RackMountRow, RackRowView, RackViewSide } from '../models/rack-overview.types';
import { RackOverviewStore } from './rack-overview-store.service';
/* ------------------------------------------------------------------------------------------------------------------ */


/**
 * The rack actions that need something the drawing does not have: a form, a confirmation, or a route.
 *
 * Every part of the view offers the same handful - place, edit, unplace, remove, open - so they live
 * here rather than being passed down as outputs through a panel that has nothing to add to them.
 *
 * Provided by the rack view, so the modals it opens belong to that view.
 */
@Injectable()
export class RackActionsService {

    private readonly store = inject(RackOverviewStore);
    private readonly fullscreenModalService = inject(FullscreenModalService);
    private readonly deleteModalService = inject(DeleteModalService);
    private readonly modalService = inject(NgbModal);
    private readonly router = inject(Router);

    /* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    /** Adds a row, on the face the view is currently showing. */
    public add(area: RackArea): void {
        this.openMountModal(null, area, null);
    }


    /** Adds a row into a slot that was clicked, pre-filled with that slot as the anchor. */
    public addAtSlot(side: RackViewSide, slot: number): void {
        this.openMountModal(null, side, slot);
    }


    /** Opens an existing row in the form, which is also the pointer-free way to place or move it. */
    public edit(mount: RackRowView): void {
        this.openMountModal(mount.row, mount.area, mount.startSlot);
    }


    /** Frees the slots but keeps the row in the rack, so it can be placed again later. */
    public unplace(mount: RackRowView): void {
        this.store.updatePlacement(mount.mountId, { area: RackArea.UNASSIGNED });
    }


    public confirmRemove(mount: RackRowView): void {
        if (!this.store.canEdit) {
            return;
        }

        this.deleteModalService.confirmDelete({
            title: 'Remove from rack',
            itemType: mount.kindTitle,
            itemName: mount.label,
            description: mount.isMount
                ? 'The object leaves the rack. The object itself is not deleted.'
                : 'The slots it holds become free again.',
            onConfirm: () => this.store.removeMount(mount.mountId)
        });
    }


    /** Only a mount has an object to open; an occupant row never reaches this. */
    public openObject(objectId: number | null): void {
        if (objectId == null) {
            return;
        }

        this.router.navigate([`/framework/object/view/${objectId}`]);
    }

    /* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    private openMountModal(mount: RackMountRow | null, presetArea: RackArea, presetStartSlot: number | null): void {
        if (!this.store.canEdit) {
            return;
        }

        // Opened through the fullscreen service: a modal parked on the body is not painted over a
        // fullscreen element, so it has to be hosted inside the rack view while that is open.
        const modalRef = this.fullscreenModalService.open(this.modalService, RackMountModalComponent, {
            size: 'lg',
            windowClass: 'dg-modal-window',
            backdropClass: 'dg-modal-window-backdrop'
        });

        modalRef.componentInstance.rackId = this.store.rackId();
        modalRef.componentInstance.rackHeight = this.store.rackHeight();
        modalRef.componentInstance.mount = mount;
        modalRef.componentInstance.presetArea = presetArea;
        modalRef.componentInstance.presetStartSlot = presetStartSlot;

        modalRef.result.then(
            (saved) => {
                if (saved) {
                    this.store.reload();
                }
            },
            () => undefined
        );
    }
}
