import { CmdbSectionTemplate } from 'src/app/framework/models/cmdb-section-template';
import { CmdbTypeSection } from 'src/app/framework/models/cmdb-type';

export interface BuilderInteractionPolicyContext {
    globalSectionTemplates: Array<CmdbSectionTemplate>;
    selectedGlobalSectionTemplates: Array<CmdbSectionTemplate>;
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

    public getSectionCollapseIcon(section: CmdbTypeSection): [string, string] {
        return this.canEditSection(section) ? ['far', 'edit'] : ['far', 'eye'];
    }

    public isSchemaLockedSection(section: CmdbTypeSection): boolean {
        const sectionName = section?.name ?? '';
        return this.context().schemaLockedSectionNames.includes(sectionName);
    }

    public isSchemaLockedField(field: any): boolean {
        const fieldName = field?.name ?? '';
        return this.context().schemaLockedFieldNames.includes(fieldName);
    }

    public isLockedSection(section: CmdbTypeSection): boolean {
        return !this.canEditSection(section);
    }

    public isLockedField(field: any): boolean {
        return this.isGlobalField(field?.name) || this.isSchemaLockedField(field);
    }

    public canEditSection(section: CmdbTypeSection): boolean {
        return !this.isGlobalSection(section) && !this.isSchemaLockedSection(section) && !this.isSystemSection(section);
    }

    public canRemoveSection(section: CmdbTypeSection): boolean {
        if (this.isGlobalSection(section)) {
            return true;
        }

        return !this.isSchemaLockedSection(section) && !this.isSystemSection(section);
    }

    public canMoveSection(section: CmdbTypeSection): boolean {
        if (this.isGlobalSection(section)) {
            return true;
        }

        return !this.isSchemaLockedSection(section) && !this.isSystemSection(section);
    }

    public canDropFieldsIntoSection(section: CmdbTypeSection): boolean {
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

    public isGlobalSection(section: CmdbTypeSection): boolean {
        const sectionName = section?.name ?? '';
        if (!sectionName) {
            return false;
        }

        const currentGlobalTemplates = this.context().globalSectionTemplates;
        const selectedGlobalTemplates = this.context().selectedGlobalSectionTemplates;

        return currentGlobalTemplates.some(template => template?.name === sectionName)
            || selectedGlobalTemplates.some(template => template?.name === sectionName);
    }

    public isGlobalField(fieldName: string): boolean {
        return this.context().globalFieldNames.includes(fieldName ?? '');
    }

    private isSystemSection(section: CmdbTypeSection): boolean {
        const sectionName = section?.name ?? '';
        return SYSTEM_SECTION_PREFIXES.some(prefix => sectionName.startsWith(prefix));
    }

    private context(): BuilderInteractionPolicyContext {
        return this.contextProvider();
    }
}
