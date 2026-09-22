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

/** Zoom, view and panel controls along the top of the canvas. */
@Component({
    selector: 'cmdb-graph-toolbar',
    standalone: false,
    templateUrl: './graph-toolbar.component.html',
    changeDetection: ChangeDetectionStrategy.OnPush,
    host: {
        'class': 'top-toolbar'
    }
})
export class GraphToolbarComponent {
    readonly zoom = input(1);
    readonly focusMode = input(false);
    readonly filterBarOpen = input(false);
    readonly legendOpen = input(false);
    readonly minimapOpen = input(false);
    readonly fullscreen = input(false);

    readonly zoomIn = output<void>();
    readonly zoomOut = output<void>();
    readonly resetZoom = output<void>();
    readonly toggleFocusMode = output<void>();
    readonly exportImage = output<void>();
    readonly toggleFilterBar = output<void>();
    readonly toggleLegend = output<void>();
    readonly toggleMinimap = output<void>();
    readonly toggleFullscreen = output<void>();
}
