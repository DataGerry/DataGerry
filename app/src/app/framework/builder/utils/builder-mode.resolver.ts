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
import { CmdbMode } from '../../modes.enum';
import { BuilderSection } from '../schema/builder-section.model';
import { BuilderContext } from './builder-context';
import { BuilderInteractionPolicy } from './builder-interaction-policy';
import { BuilderUtils } from './builder-utils';
/* ------------------------------------------------------------------------------------------------------------------ */

/**
 * Decides which CmdbMode a section's or a field's config editor is mounted in.
 *
 * That mode is what makes an identifier editable: `disableControlOnEdit` clears the name
 * validators in Edit mode, `disableControlsOnGlobal` disables name and label in Global mode.
 * The highlight helper asks the same question, so the rule lives here rather than in the canvas
 * template - otherwise a saved identifier could be flagged as invalid by a validator that was
 * never applied to it.
 */
export class BuilderModeResolver {

    constructor(
        private readonly ctx: BuilderContext,
        private readonly policy: BuilderInteractionPolicy
    ) {}


    public sectionMode(section: BuilderSection): CmdbMode {
        if (!this.policy.canEditSection(section)) {
            return CmdbMode.Global;
        }

        if (this.isNewSection(section)) {
            return CmdbMode.Create;
        }

        return this.ctx.mode;
    }


    public fieldMode(field: any): CmdbMode {
        return this.isNewField(field) ? CmdbMode.Create : this.ctx.mode;
    }


    public isNewSection(section: BuilderSection): boolean {
        return BuilderUtils?.isNewSection(section, this.ctx.newSections);
    }


    public isNewField(field: any): boolean {
        return BuilderUtils?.isNewField(field, this.ctx.newFields) || this.isFieldAddedDuringEdit(field);
    }


    private isFieldAddedDuringEdit(field: any): boolean {
        if (this.ctx.mode !== CmdbMode.Edit || !field?.name || !this.ctx.initialFieldNames) {
            return false;
        }

        return !this.ctx.initialFieldNames.has(field.name) && !this.policy.isSchemaLockedField(field);
    }
}
