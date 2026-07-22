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
import { v4 as uuidv4 } from 'uuid';

import { CmdbSectionTemplate } from '../../../models/cmdb-section-template';
import { CmdbTypeSection } from '../../../models/cmdb-type';
import { BuilderContext } from './builder-context';
import { BuilderInteractionPolicy } from './builder-interaction-policy';

/**
 * Handles the global/section template palette bookkeeping and the generation of unique
 * section/field identifiers. All state is read/written through the shared BuilderContext.
 */
export class BuilderTemplateManager {
    constructor(
        private readonly ctx: BuilderContext,
        private readonly policy: BuilderInteractionPolicy
    ) {}

    public setSelectedGlobalTemplates(): void {
        if (this.ctx.typeInstance?.global_template_ids?.length > 0) {
            // iterate global_template_ids
            this.ctx.typeInstance?.global_template_ids?.forEach((globalTemplateName) => {

                let index: number = -1;

                for (let templateIndex in this.ctx.globalSectionTemplates) {
                    let aTemplate = this.ctx.globalSectionTemplates[templateIndex];

                    if (aTemplate?.name == globalTemplateName) {
                        this.ctx.selectedGlobalSectionTemplates?.push(aTemplate);
                        index = Number(templateIndex);
                    }
                }

                this.ctx.globalSectionTemplates?.splice(index, 1);
            })
        }
    }

    public handleGlobalTemplates(sectionData: CmdbTypeSection): void {
        let isGlobalTemplate = false;
        let globalTemplateIndex: number = -1;

        for (let index in this.ctx.selectedGlobalSectionTemplates) {
            const aSection = this.ctx.selectedGlobalSectionTemplates[index];
            if (aSection?.name == sectionData?.name) {
                isGlobalTemplate = true;
                globalTemplateIndex = parseInt(index);
                this.ctx.globalSectionTemplates?.push(aSection);
                this.ctx.globalSectionTemplates?.sort((a, b) => a?.public_id - b?.public_id);
            }
        }

        if (isGlobalTemplate) {
            const nameIndex = this.ctx.typeInstance?.global_template_ids?.indexOf(sectionData?.name, 0);
            this.ctx.typeInstance?.global_template_ids?.splice(nameIndex, 1);
            this.ctx.selectedGlobalSectionTemplates?.splice(globalTemplateIndex, 1);
        }
    }

    /**
     * Extracts the section properties from the section template.
     */
    public extractSectionData(data: CmdbSectionTemplate) {
        let sectionName: string = data?.name;

        if (!data?.is_global && !this.isUniqueID(sectionName)) {
            sectionName = this.createUniqueID('section_template');
        }

        return {
            'name': sectionName,
            'label': data.label,
            'type': data.type,
            'fields': data.fields,
            'bg_color': '#ffffff'
        }
    }

    /**
     * Sets the fields from the section template to the type instance.
     */
    public setSectionTemplateFields(sectionTemplate: CmdbSectionTemplate): void {
        let sectionTemplateFields = sectionTemplate?.fields;

        for (let fieldIndex in sectionTemplateFields) {
            let aField = sectionTemplateFields[fieldIndex];

            if (!this.policy.isGlobalField(aField?.name) && !this.isUniqueID(aField?.name)) {
                aField.name = this.createUniqueID(aField?.type);
            }

            this.ctx.newFields?.push(aField);
            this.ctx.typeInstance?.fields?.push(aField);
        }

        this.ctx.typeInstance.fields = [...this.ctx.typeInstance.fields];
    }

    /**
     * Creates a unique name for section templates and fields if a section template is added more than once.
     */
    public getUniqueName(name: string): string {
        return this.createUniqueID(name);
    }

    /**
     * Creates a unique ID for a field or section.
     */
    private createUniqueID(name: string): string {
        const uniqueID = `${name}-${uuidv4()}`;

        // if ID is already used then create a new one
        if (this.isUniqueID(uniqueID)) {
            return uniqueID;
        } else {
            return this.createUniqueID(name);
        }
    }

    /**
     * Checks if the given ID already exists for a field or section.
     */
    private isUniqueID(uniqueID: string): boolean {
        //first check all field names
        for (let fieldIndex in this.ctx.typeInstance?.fields) {
            let currentField = this.ctx.typeInstance?.fields[fieldIndex];

            if (currentField?.name == uniqueID) {
                return false;
            }
        }

        //check all section names
        for (let sectionIndex in this.ctx.typeInstance?.render_meta?.sections) {
            let currentSection = this.ctx.typeInstance?.render_meta?.sections[sectionIndex];

            if (currentSection?.name == uniqueID) {
                return false;
            }
        }

        return true;
    }
}
