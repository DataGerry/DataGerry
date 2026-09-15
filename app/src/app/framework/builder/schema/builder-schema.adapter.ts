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
/* ------------------------------------------------------------------------------------------------------------------ */

/**
 * Where a builder keeps its sections and fields.
 *
 * A type nests them under `render_meta`, a relation keeps them at the root, but at rest both hold
 * the same shape: `sections[]` referencing field names plus one flat `fields[]`. This adapter is
 * the only thing in the kernel that knows which of the two it is looking at.
 *
 * Two contracts every implementation must honour:
 *
 * - `writeSections` / `writeFields` must assign a **fresh array**. The canvas `ngDoCheck` and the
 *   wizard steps' `KeyValueDiffer` both detect replacement, not mutation.
 * - `readSections` / `readFields` must return the **live** array, because removal splices it.
 */
export interface BuilderSchemaAdapter {

    readSections(): Array<BuilderSection>;
    writeSections(sections: Array<BuilderSection>): void;

    readFields(): Array<any>;
    writeFields(fields: Array<any>): void;

    /** External links declared on the model; empty where the model has none. */
    readExternals(): Array<any>;

    /** Names of the applied global section templates; empty where templates are not supported. */
    readGlobalTemplateIds(): Array<string>;

    /** Applies the Location control's "selectable as parent" flag; a no-op where it has no meaning. */
    setSelectableAsParent(value: boolean): void;

    /** Whether the model declares port support; false and a no-op where it has no meaning. */
    readUsesPorts(): boolean;
    setUsesPorts(value: boolean): void;
}
