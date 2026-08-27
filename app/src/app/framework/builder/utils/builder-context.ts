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
import { CmdbType, CmdbTypeSection } from '../../models/cmdb-type';
import { CmdbMode } from '../../modes.enum';

/**
 * Shared, mutable state of the type builder.
 */
export interface BuilderContext {
    sections: Array<any>;
    typeInstance: CmdbType;
    newSections: Array<CmdbTypeSection>;
    newFields: Array<CmdbTypeSection>;

    globalSectionTemplates: Array<CmdbSectionTemplate>;
    selectedGlobalSectionTemplates: Array<CmdbSectionTemplate>;
    lockedSectionNames: Array<string>;
    lockedFieldNames: Array<string>;

    disableFields: boolean;
    mode: CmdbMode;

    activeIndex: number | null;
    draggedSectionIndex: number | null;
    pendingSectionDropIndex: number | null;
    draggedField: { field: any; section: CmdbTypeSection; index: number } | null;
    activeDuplicateField: { sectionIndex: number; fieldIndex: number } | null;

    prevSectionHighlighted: boolean;
    prevFieldHighlighted: boolean;
    sectionReference: Array<any> | null;
    initialFieldNames: Set<string> | null;
    initialIdentifier: string;
}
