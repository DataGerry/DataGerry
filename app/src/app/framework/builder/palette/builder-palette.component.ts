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
* along with this program.  If not, see <https://www.gnu.org/licenses/>.
*/
import { ChangeDetectionStrategy, Component, input } from '@angular/core';

import { DndModule } from 'ngx-drag-drop';

import { LayoutModule } from '../../../layout/layout.module';
import { BuilderPaletteGroup } from './builder-palette.model';
/* ------------------------------------------------------------------------------------------------------------------ */

/**
 * The builder's control palette: one collapsible card per group of draggable items.
 * Shared by the type, relation and section template builders, which differ only in
 * which groups they pass in.
 *
 * Projected content is rendered below the panel - the type builder puts its Preview and
 * Diagnostic actions there.
 */
@Component({
    selector: 'dg-builder-palette',
    standalone: true,
    imports: [DndModule, LayoutModule],
    templateUrl: './builder-palette.component.html',
    styleUrls: ['./builder-palette.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    host: { '[class.fill-height]': 'fillHeight()' }
})
export class BuilderPaletteComponent {

    public readonly groups = input.required<ReadonlyArray<BuilderPaletteGroup>>();

    /** Stops items being dragged while the canvas has an unresolved error. */
    public readonly dragDisabled = input(false);

    /** Covers the whole panel, e.g. while the step is invalid. */
    public readonly blocked = input(false);

    /**
     * Stretches the panel to its column height. The type builder sets this before the first
     * section is dropped so the palette lines up with the empty drop zone.
     */
    public readonly fillHeight = input(false);
}
