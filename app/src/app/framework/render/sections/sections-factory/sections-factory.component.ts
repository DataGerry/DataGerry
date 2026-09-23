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
import { Component, Input, OnChanges, TemplateRef } from '@angular/core';

import { CmdbType, CmdbTypeSection } from '../../../models/cmdb-type';
import { BaseSectionComponent } from '../base-section/base-section.component';
import { RenderResult } from 'src/app/framework/models/cmdb-render';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'cmdb-sections-factory',
    templateUrl: './sections-factory.component.html',
    styleUrls: ['./sections-factory.component.scss'],
    standalone: false
})
export class SectionsFactoryComponent extends BaseSectionComponent implements OnChanges {
    @Input() public sections: Array<CmdbTypeSection> = [];
    @Input() objectID: number;
    @Input() public typeInstance: CmdbType;
    @Input() public renderResult: RenderResult;

    /** A surface the type does not store as a section, placed among the sections it does. */
    @Input() public sectionSlot: TemplateRef<unknown> | null = null;
    @Input() public sectionSlotIndex: number | null = null;

    /** The position the slot renders in, or null while there is nothing to place. */
    public resolvedSlotIndex: number | null = null;

    constructor() {
        super();

    
    }

/* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    public ngOnChanges(): void {
        this.resolvedSlotIndex = this.resolveSlotIndex();
    }

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    /** A stored slot may outrun the sections it was measured against, so it is clamped, never dropped. */
    private resolveSlotIndex(): number | null {
        if (!this.sectionSlot || this.sectionSlotIndex == null) {
            return null;
        }

        const sectionCount = this.sections?.length ?? 0;

        return Math.min(Math.max(this.sectionSlotIndex, 0), sectionCount);
    }
}
