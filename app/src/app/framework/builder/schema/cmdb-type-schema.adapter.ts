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
import { CmdbType } from '../../models/cmdb-type';
import { BuilderSection } from './builder-section.model';
import { BuilderSchemaAdapter } from './builder-schema.adapter';
/* ------------------------------------------------------------------------------------------------------------------ */

/** A type keeps its sections under `render_meta` and its fields at the root. */
export class CmdbTypeSchemaAdapter implements BuilderSchemaAdapter {

    /**
     * Stand-in for a model that has not been shaped yet. It is a single instance so the canvas'
     * `ngDoCheck` identity check does not see a brand new array on every pass.
     */
    private readonly missing: Array<any> = [];

    constructor(private readonly typeInstance: CmdbType) {}


    public readSections(): Array<BuilderSection> {
        const meta = this.typeInstance?.render_meta;

        if (!meta) {
            return this.missing;
        }

        if (!meta.sections) {
            meta.sections = [];
        }

        return meta.sections as Array<BuilderSection>;
    }


    public writeSections(sections: Array<BuilderSection>): void {
        this.typeInstance.render_meta.sections = [...sections];
    }


    public readFields(): Array<any> {
        if (!this.typeInstance) {
            return this.missing;
        }

        if (!this.typeInstance.fields) {
            this.typeInstance.fields = [];
        }

        return this.typeInstance.fields;
    }


    public writeFields(fields: Array<any>): void {
        this.typeInstance.fields = [...fields];
    }


    public readExternals(): Array<any> {
        return this.typeInstance?.render_meta?.externals ?? [];
    }


    public readGlobalTemplateIds(): Array<string> {
        return this.typeInstance?.global_template_ids ?? [];
    }


    public setSelectableAsParent(value: boolean): void {
        this.typeInstance.selectable_as_parent = value;
    }


    public readUsesPorts(): boolean {
        return this.typeInstance?.uses_ports === true;
    }


    public setUsesPorts(value: boolean): void {
        this.typeInstance.uses_ports = value;
    }
}
