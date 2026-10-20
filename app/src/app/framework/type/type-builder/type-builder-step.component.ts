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
import { Directive, Input } from '@angular/core';

import { BuilderWizardStepComponent } from 'src/app/framework/builder/wizard/builder-wizard-step.component';
import { CmdbType } from '../../models/cmdb-type';
import { Group } from '../../../management/models/group';
/* ------------------------------------------------------------------------------------------------------------------ */

/**
 * Base class for every step of the type wizard: the shared step contract plus the type it edits.
 */
@Directive()
export abstract class TypeBuilderStepComponent extends BuilderWizardStepComponent {

  /**
   * Type instance
   */
  @Input() public typeInstance: CmdbType;

  /**
   * List of all possible groups
   */
  @Input() public groups: Array<Group> = [];
}
