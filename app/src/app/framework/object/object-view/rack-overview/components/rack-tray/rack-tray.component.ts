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

import { RackArea } from '../../models/rack-overview.types';
import { RackActionsService } from '../../services/rack-actions.service';
import { RackDragService } from '../../services/rack-drag.service';
import { RackOverviewStore } from '../../services/rack-overview-store.service';
/* ------------------------------------------------------------------------------------------------------------------ */


/**
 * The staging card, for rows that are in the rack but hold no slot.
 *
 * It is also the way back out of the elevation, so the whole card is a drop target: the handlers sit
 * on the host rather than inside, which is what lets a row be released anywhere over it.
 */
@Component({
    selector: 'cmdb-rack-tray',
    templateUrl: './rack-tray.component.html',
    styleUrls: ['./rack-tray.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    host: {
        'class': 'rack-tray',
        '[class.rack-tray--drop-ready]': 'isDropReady()',
        '(dragover)': 'drag.onAreaDragOver($event, AREAS.UNASSIGNED)',
        '(dragleave)': 'drag.onAreaDragLeave($event)',
        '(drop)': 'drag.onAreaDrop($event, AREAS.UNASSIGNED)'
    },
    standalone: false
})
export class RackTrayComponent {

    public readonly store = inject(RackOverviewStore);
    public readonly drag = inject(RackDragService);
    public readonly actions = inject(RackActionsService);

    /** Where the tooltips of this card are parked, which fullscreen changes. */
    public readonly tooltipContainer = input<string | null>('body');

    public readonly AREAS = RackArea;

    public readonly isDropReady = computed(() => this.drag.targetArea() === RackArea.UNASSIGNED);

    /** Set while a row this card would take is in flight, so it can say what it would do with it. */
    public readonly acceptsDrag = computed(() => this.drag.droppableAreas().has(RackArea.UNASSIGNED));
}
