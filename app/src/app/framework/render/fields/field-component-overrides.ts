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
import { InjectionToken, Type } from '@angular/core';

import { CmdbMode } from '../../modes.enum';
/* ------------------------------------------------------------------------------------------------------------------ */

/**
 * Lets a feature module replace the render component used for one specific field (matched by
 * its {@code data.name}) without the generic render dispatcher importing that feature. The
 * dispatcher consults the registered overrides before falling back to the type-default field
 * component, mirroring the {@code MDS_ROW_VALIDATORS} plugin seam.
 */
export interface FieldComponentOverride {
    /** Exact field name ({@code data.name}) this override applies to. */
    fieldName: string;

    /** Component rendered instead of the type-default field component. */
    component: Type<unknown>;

    /** Modes the override applies to. When omitted it applies to every supported mode. */
    modes?: ReadonlyArray<CmdbMode>;
}

export const FIELD_COMPONENT_OVERRIDES = new InjectionToken<ReadonlyArray<FieldComponentOverride>>(
    'FieldComponentOverrides'
);
