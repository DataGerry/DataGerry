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
import { BuilderSection } from './builder-section.model';
import { BuilderSchemaAdapter } from './builder-schema.adapter';
/* ------------------------------------------------------------------------------------------------------------------ */

/**
 * Stands in for a model the canvas has not been given yet - a wizard step whose instance is still
 * loading, for instance. Reads report an empty model and writes are dropped, so the canvas and its
 * helpers run their normal code paths instead of null-checking the schema at every call site.
 *
 * The arrays are per-instance and never replaced, which keeps the canvas' `ngDoCheck` identity
 * check stable while nothing is bound.
 */
export class EmptySchemaAdapter implements BuilderSchemaAdapter {

    private readonly sections: Array<BuilderSection> = [];
    private readonly fields: Array<any> = [];
    private readonly externals: Array<any> = [];
    private readonly globalTemplateIds: Array<string> = [];

    public readSections(): Array<BuilderSection> {
        return this.sections;
    }

    public writeSections(): void {
        // Nothing to write to.
    }

    public readFields(): Array<any> {
        return this.fields;
    }

    public writeFields(): void {
        // Nothing to write to.
    }

    public readExternals(): Array<any> {
        return this.externals;
    }

    public readGlobalTemplateIds(): Array<string> {
        return this.globalTemplateIds;
    }

    public setSelectableAsParent(): void {
        // Nothing to write to.
    }
}
