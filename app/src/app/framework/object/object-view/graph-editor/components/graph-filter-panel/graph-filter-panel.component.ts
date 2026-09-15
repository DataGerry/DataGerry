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

* You should have received a copy of the GNU Affero General Public License
* along with this program. If not, see <https://www.gnu.org/licenses/>.
*/
import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';
import { FormGroup } from '@angular/forms';

import { CI_EXPLORER_EDIT_RIGHT } from 'src/app/framework/models/ci-explorer.model';

import { FilterProfile } from '../../interfaces/graph.interfaces';

export type FilterMode = 'manual' | 'profile';

export interface FilterOption {
    public_id: number;
    display_name: string;
}

/** The collapsible filter bar: manual type/relation pickers, or a saved profile. */
@Component({
    selector: 'cmdb-graph-filter-panel',
    templateUrl: './graph-filter-panel.component.html',
    changeDetection: ChangeDetectionStrategy.OnPush,
    host: {
        'class': 'filter-bar-container',
        '[class.visible]': 'open()'
    },
    standalone: false
})
export class GraphFilterPanelComponent {
    /** Filter profiles are written through the CI Explorer edit routes, so their controls need that right. */
    readonly ciExplorerEditRight = CI_EXPLORER_EDIT_RIGHT;

    readonly open = input(false);
    readonly mode = input<FilterMode>('manual');
    readonly form = input.required<FormGroup>();
    readonly typeOptions = input<FilterOption[]>([]);
    readonly relationOptions = input<FilterOption[]>([]);
    readonly profiles = input<FilterProfile[]>([]);
    readonly selectedProfileId = input<number | null>(null);
    readonly withLocations = input(true);
    readonly withIpamRelations = input(true);

    readonly modeChange = output<FilterMode>();
    readonly selectedProfileIdChange = output<number | null>();
    readonly applyFilters = output<void>();
    readonly clearFilters = output<void>();
    readonly saveAsProfile = output<void>();
    readonly applyProfile = output<void>();
    readonly manageProfiles = output<void>();
    readonly withLocationsChange = output<boolean>();
    readonly withIpamRelationsChange = output<boolean>();
}
