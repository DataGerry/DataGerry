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
import { InjectionToken } from '@angular/core';

import { BuilderSection } from '../schema/builder-section.model';
/* ------------------------------------------------------------------------------------------------------------------ */

/** Which of the two delete actions is being guarded. */
export type BuilderDeletionScope = 'field' | 'section';

/**
 * Lets a feature veto a removal the builder would otherwise perform. The type builder provides one
 * so a location field still referenced by objects cannot be deleted; builders without such a rule
 * simply do not provide the token.
 *
 * The check must stay synchronous - the guard is consulted from the click handler.
 */
export interface BuilderDeletionGuard {

    /** True when the field itself is guarded. */
    isLocationField(field: any): boolean;

    /** True when the section holds a guarded field. `fields` is the builder's flat field list. */
    sectionContainsLocationField(section: BuilderSection, fields: Array<any>): boolean;

    /** Returns false to block the removal; showing the explanatory modal is the guard's job. */
    canDelete(scope: BuilderDeletionScope): boolean;
}

export const BUILDER_DELETION_GUARD = new InjectionToken<BuilderDeletionGuard>('BuilderDeletionGuard');
