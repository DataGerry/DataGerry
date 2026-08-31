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
import { Component, Input } from '@angular/core';

import { CmdbMode } from '../../modes.enum';
import { BuilderSection } from '../schema/builder-section.model';
import { BuilderUtils } from '../utils/builder-utils';
import { BuilderSectionHost } from './builder-section-host';
/* ------------------------------------------------------------------------------------------------------------------ */

/**
 * One section card: its config editor, the field dropzone and the field cards.
 *
 * The canvas repeats it once per section; the section template page shows exactly one. Everything
 * that differs between the two comes from the injected host, so the card holds no builder state of
 * its own and only derives what the template needs.
 *
 * Deliberately not OnPush: the whole card is a projection of mutable model state that changes
 * without any input reference changing, exactly as it did while this markup lived in the canvas.
 */
@Component({
    selector: 'dg-builder-section',
    templateUrl: './builder-section.component.html',
    styleUrls: ['./builder-section.component.scss'],
    standalone: false
})
export class BuilderSectionComponent {

    @Input() public section: BuilderSection;
    @Input() public index: number = 0;
    @Input() public host: BuilderSectionHost;

    public readonly MODES: typeof CmdbMode = CmdbMode;

    /* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    /** Bootstrap collapse target. Follows the identifier, so renaming a section keeps its toggle working. */
    public get collapseId(): string {
        return `section-${this.index}${this.section?.name ?? ''}`;
    }

    public fieldCollapseId(field: any, fieldIndex: number): string {
        return `field-${this.index}${fieldIndex}${field?.name ?? ''}`;
    }

    /** Mirrors the palette icon of the control the section was dragged from. */
    public get sectionIcon(): [string, string] {
        return BuilderUtils.matchedSectionType(this.section?.type);
    }

    public get holdsFields(): boolean {
        return this.section?.type === 'section' || this.section?.type === 'multi-data-section';
    }

    public get sectionDragDisabled(): boolean {
        return !this.host.canMoveSection(this.section) || this.host.isAnySectionHighlighted() || this.host.disableFields;
    }

    public fieldDragDisabled(field: any): boolean {
        return this.host.isLocked()
            || this.host.disableFields
            || this.host.isAnySectionHighlighted()
            || !this.host.canMoveField(field);
    }
}
