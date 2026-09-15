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

import { RackArea } from '../../models/rack-overview.types';
import { RackActionsService } from '../../services/rack-actions.service';
import { RackOverviewStore } from '../../services/rack-overview-store.service';
/* ------------------------------------------------------------------------------------------------------------------ */


/** The card that reads out the row selected in the drawing, and the actions that apply to it. */
@Component({
    selector: 'cmdb-rack-inspector',
    templateUrl: './rack-inspector.component.html',
    styleUrls: ['./rack-inspector.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    host: { 'class': 'rack-inspector', 'aria-live': 'polite' },
    standalone: false
})
export class RackInspectorComponent {

    public readonly store = inject(RackOverviewStore);
    public readonly actions = inject(RackActionsService);

    public readonly AREAS = RackArea;
}
