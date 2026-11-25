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
import { ChangeDetectionStrategy, Component, inject } from '@angular/core';

import { GroupSyncStore } from '../../services/group-sync.store';
import { SyncPassSummaryComponent } from '../../../person-sync/components/sync-pass-summary.component';
/* ------------------------------------------------------------------------------------------------------------------ */

/** The synced persons the last mapping took out of its person group. */
@Component({
    selector: 'app-group-map-summary',
    standalone: true,
    imports: [SyncPassSummaryComponent],
    templateUrl: './group-map-summary.component.html',
    styleUrls: ['./group-map-summary.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush
})
export class GroupMapSummaryComponent {

    protected readonly store = inject(GroupSyncStore);
}
