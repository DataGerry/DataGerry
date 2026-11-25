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
import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import { RouterLink } from '@angular/router';
import { NgbModal } from '@ng-bootstrap/ng-bootstrap';

import { CoreModule } from 'src/app/core/core.module';
import { FullscreenModalService } from 'src/app/core/services/fullscreen-modal.service';
import { Group } from '../../../models/group';
import { GroupMappingRequest } from '../../../models/person-sync';
import { GroupSyncStore } from '../../services/group-sync.store';
import { GroupMapModalComponent } from '../../modals/group-map-modal/group-map-modal.component';
/* ------------------------------------------------------------------------------------------------------------------ */

/** "Mapped to X" of one user group, with Map / Unmap. */
@Component({
    selector: 'app-group-mapping-cell',
    standalone: true,
    imports: [CoreModule, RouterLink],
    changeDetection: ChangeDetectionStrategy.OnPush,
    templateUrl: './group-mapping-cell.component.html',
    styleUrls: ['./group-mapping-cell.component.scss']
})
export class GroupMappingCellComponent {

    protected readonly store = inject(GroupSyncStore);
    private readonly modalService = inject(NgbModal);
    private readonly fullscreenModal = inject(FullscreenModalService);

    public readonly group = input<Group | null>(null);

    protected readonly mapping = computed(() => {
        const group = this.group();

        return group ? (this.store.mappingsByUserGroup().get(group.public_id) ?? null) : null;
    });

    protected readonly groupName = computed(() => this.group()?.label || this.group()?.name || '');

/* ---------------------------------------------------- EVENTS ------------------------------------------------------ */

    protected onMap(): void {
        const group = this.group();
        const modal = this.modalService.open(GroupMapModalComponent, this.fullscreenModal.withFullscreenContainer({
            size: 'lg',
            windowClass: 'dg-modal-window',
            backdropClass: 'dg-modal-window-backdrop',
            ariaLabelledBy: 'group-map-title'
        }));

        (modal.componentInstance as GroupMapModalComponent).groupLabel.set(this.groupName());

        modal.result.then(
            (request: GroupMappingRequest) => this.store.map(group.public_id, request, this.groupName()),
            () => undefined
        );
    }


    protected onUnmap(): void {
        this.store.unmap(this.group().public_id, this.groupName());
    }
}
