import { CmdbSectionTemplate } from 'src/app/framework/models/cmdb-section-template';
import { BuilderSection } from '../schema/builder-section.model';

export interface BuilderInteractionPolicyContext {
    selectedGlobalSectionTemplates: Array<CmdbSectionTemplate>;
    globalTemplateIds: Array<string>;
    globalFieldNames: Array<string>;
    schemaLockedSectionNames: Array<string>;
    schemaLockedFieldNames: Array<string>;
}

const SYSTEM_SECTION_PREFIXES = ['dg_gst-'];

/**
 * Builder interaction rules (single source of truth):
 * - Global template sections: not editable, movable, removable, no field drop.
 * - Schema-locked sections: not editable, movable, not removable, no field drop.
 * - System sections (dg_gst-/dg-): not editable, not movable, not removable, no field drop.
 * - Global/schema locked fields: not editable, not movable, not removable.
 */
export class BuilderInteractionPolicy {
    constructor(private readonly contextProvider: () => BuilderInteractionPolicyContext) {}

    public getSectionCollapseIcon(section: BuilderSection): [string, string] {
        return this.canEditSection(section) ? ['far', 'edit'] : ['far', 'eye'];
    }

    public isSchemaLockedSection(section: BuilderSection): boolean {
        const sectionName = section?.name ?? '';
        return this.context().schemaLockedSectionNames.includes(sectionName);
    }

    public isSchemaLockedField(field: any): boolean {
        const fieldName = field?.name ?? '';
        return this.context().schemaLockedFieldNames.includes(fieldName);
    }

    public isLockedSection(section: BuilderSection): boolean {
        return !this.canEditSection(section);
    }

    public isLockedField(field: any): boolean {
        return this.isGlobalField(field?.name) || this.isSchemaLockedField(field);
    }

    public canEditSection(section: BuilderSection): boolean {
        return !this.isGlobalSection(section) && !this.isSchemaLockedSection(section) && !this.isSystemSection(section);
    }

    public canRemoveSection(section: BuilderSection): boolean {
        if (this.isGlobalSection(section)) {
            return true;
        }

        return !this.isSchemaLockedSection(section) && !this.isSystemSection(section);
    }

    public canMoveSection(section: BuilderSection): boolean {
        if (this.isGlobalSection(section)) {
            return true;
        }

        return !this.isSchemaLockedSection(section) && !this.isSystemSection(section);
    }

    public canDropFieldsIntoSection(section: BuilderSection): boolean {
        return !this.isGlobalSection(section) && !this.isSchemaLockedSection(section) && !this.isSystemSection(section);
    }

    public canEditField(field: any): boolean {
        return !this.isLockedField(field);
    }

    public canRemoveField(field: any): boolean {
        return !this.isLockedField(field);
    }

    public canMoveField(field: any): boolean {
        return !this.isLockedField(field);
    }

    public isGlobalSection(section: BuilderSection): boolean {
        const sectionName = section?.name;
        if (!sectionName) {
            return false;
        }

        const context = this.context();

        if (context.globalTemplateIds?.includes(sectionName)) {
            return true;
        }

        return context.selectedGlobalSectionTemplates.some(template => template?.name === sectionName);
    }

    public isGlobalField(fieldName: string): boolean {
        if (!fieldName) {
            return false;
        }

        return this.context().globalFieldNames.includes(fieldName);
    }

    private isSystemSection(section: BuilderSection): boolean {
        const sectionName = section?.name ?? '';
        return SYSTEM_SECTION_PREFIXES.some(prefix => sectionName.startsWith(prefix));
    }

    private context(): BuilderInteractionPolicyContext {
        return this.contextProvider();
    }
}
