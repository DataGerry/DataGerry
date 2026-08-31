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
import { CmdbSectionTemplate } from '../../models/cmdb-section-template';
import { CmdbMode } from '../../modes.enum';
import { BuilderSection } from '../schema/builder-section.model';
import { BuilderSchemaAdapter } from '../schema/builder-schema.adapter';
/* ------------------------------------------------------------------------------------------------------------------ */

/**
 * Shared, mutable state of a builder canvas. The edited model is only ever reached through
 * `schema`, which is what keeps the kernel free of `render_meta`.
 */
export interface BuilderContext {
    /** Hydrated projection of the model's sections: field names resolved to field objects. */
    sections: Array<BuilderSection>;

    schema: BuilderSchemaAdapter;

    newSections: Array<BuilderSection>;
    newFields: Array<any>;

    globalSectionTemplates: Array<CmdbSectionTemplate>;
    selectedGlobalSectionTemplates: Array<CmdbSectionTemplate>;
    lockedSectionNames: Array<string>;
    lockedFieldNames: Array<string>;

    disableFields: boolean;
    mode: CmdbMode;

    activeIndex: number | null;
    draggedSectionIndex: number | null;
    pendingSectionDropIndex: number | null;
    draggedField: { field: any; section: BuilderSection; index: number } | null;
    activeDuplicateField: { sectionIndex: number; fieldIndex: number } | null;

    prevSectionHighlighted: boolean;
    prevFieldHighlighted: boolean;
    sectionReference: Array<BuilderSection> | null;
    initialFieldNames: Set<string> | null;
    initialIdentifier: string;
}
