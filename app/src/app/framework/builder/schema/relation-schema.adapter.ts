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
import { CmdbRelation } from '../../models/relation.model';
import { BuilderSection } from './builder-section.model';
import { BuilderSchemaAdapter } from './builder-schema.adapter';
/* ------------------------------------------------------------------------------------------------------------------ */

/**
 * A relation keeps sections and fields at the root. It has no external links, no section
 * templates and no location control, so those three reads report "nothing here".
 */
export class RelationSchemaAdapter implements BuilderSchemaAdapter {

    /** Stand-in for a missing model; a single instance keeps the canvas' identity check stable. */
    private readonly missing: Array<any> = [];

    constructor(private readonly relationInstance: CmdbRelation) {}


    public readSections(): Array<BuilderSection> {
        if (!this.relationInstance) {
            return this.missing;
        }

        if (!this.relationInstance.sections) {
            this.relationInstance.sections = [];
        }

        return this.relationInstance.sections as unknown as Array<BuilderSection>;
    }


    public writeSections(sections: Array<BuilderSection>): void {
        this.relationInstance.sections = [...sections] as any;
    }


    public readFields(): Array<any> {
        if (!this.relationInstance) {
            return this.missing;
        }

        if (!this.relationInstance.fields) {
            this.relationInstance.fields = [];
        }

        return this.relationInstance.fields;
    }


    public writeFields(fields: Array<any>): void {
        this.relationInstance.fields = [...fields];
    }


    public readExternals(): Array<any> {
        return [];
    }


    public readGlobalTemplateIds(): Array<string> {
        return [];
    }


    public setSelectableAsParent(): void {
        // A relation has no location control, so there is no parent-selectability flag to set.
    }


    public readUsesPorts(): boolean {
        return false;
    }


    public setUsesPorts(): void {
        // A relation has no ports.
    }
}
