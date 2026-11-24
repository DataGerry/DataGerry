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
import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import { RouterLink } from '@angular/router';

import { SyncPassCounts } from '../../models/person-sync';
import { summarizeSyncPass } from '../person-sync-pass.util';
/* ------------------------------------------------------------------------------------------------------------------ */

/** What a sync pass wrote: its counts and the synced persons it took out of mapped person groups. */
@Component({
    selector: 'app-sync-pass-summary',
    standalone: true,
    imports: [RouterLink],
    changeDetection: ChangeDetectionStrategy.OnPush,
    templateUrl: './sync-pass-summary.component.html',
    styleUrls: ['./sync-pass-summary.component.scss']
})
export class SyncPassSummaryComponent {

    public readonly pass = input.required<SyncPassCounts>();

    protected readonly summary = computed(() => summarizeSyncPass(this.pass()));
}
