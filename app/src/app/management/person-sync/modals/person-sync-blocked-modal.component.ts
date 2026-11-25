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
import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { NgbActiveModal } from '@ng-bootstrap/ng-bootstrap';

import { CoreModule } from 'src/app/core/core.module';
import { DgModalComponent } from 'src/app/core/components/modal/dg-modal.component';
import { BlockedPersonRow } from '../../models/person-sync';
/* ------------------------------------------------------------------------------------------------------------------ */

export const BLOCKED_COPY_RESULT = 'copy';


@Component({
    selector: 'app-person-sync-blocked-modal',
    standalone: true,
    imports: [CoreModule, DgModalComponent],
    changeDetection: ChangeDetectionStrategy.OnPush,
    templateUrl: './person-sync-blocked-modal.component.html',
    styleUrls: ['./person-sync-blocked-modal.component.scss']
})
export class PersonSyncBlockedModalComponent {

    public readonly activeModal = inject(NgbActiveModal);

    public readonly rows = signal<BlockedPersonRow[]>([]);

    protected readonly copyResult = BLOCKED_COPY_RESULT;

    protected readonly blockedRows = computed(() => this.rows().filter(row => row.blockers.length > 0));

    protected readonly blockedCount = computed(() => this.blockedRows().length);
}
