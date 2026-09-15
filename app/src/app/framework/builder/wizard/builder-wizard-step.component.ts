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
import { Directive, EventEmitter, Input, Output } from '@angular/core';

import { CmdbMode } from '../../modes.enum';
import { CmdbType } from '../../models/cmdb-type';
/* ------------------------------------------------------------------------------------------------------------------ */

/**
 * What every builder wizard step is driven by, regardless of what it edits: the render mode it was
 * mounted in, the types it can reference, and its validity back to the wizard.
 *
 * Selectorless on purpose - it is a base class, never a declared component.
 */
@Directive()
export abstract class BuilderWizardStepComponent {

    /** Render modes, for templates that branch on the current one. */
    public modes = CmdbMode;

    /** Selected render mode. */
    @Input() public mode: CmdbMode = CmdbMode.View;

    /** List of possible types. */
    @Input() public types: Array<CmdbType> = [];

    /** Is the step valid. */
    @Input() public valid: boolean = true;

    /** Validation change emitter. */
    @Output() public validateChange: EventEmitter<boolean> = new EventEmitter<boolean>();
}
