import { FieldIdentifierValidationService } from "src/app/framework/builder/services/field-identifier-validation.service";
import { BuilderSchemaAdapter } from "../schema/builder-schema.adapter";
import { BuilderSection } from "../schema/builder-section.model";
import { NgbModal } from "@ng-bootstrap/ng-bootstrap";
import { DiagnosticModalComponent } from "../modals/diagnostic-modal/diagnostic-modal.component";
import { PreviewModalComponent } from "../modals/preview-modal/preview-modal.component";
import { BuilderIcon, MULTI_DATA_SECTION_ICON, REF_SECTION_ICON, SECTION_ICON } from "./builder-icons";

export class BuilderUtils {

    /**
     * Retrieves the index of a field in the edited model based on the targetName.
     * @param schema Schema adapter of the edited model.
     * @param targetName The name of the field to search for.
     * @returns The index of the field, or -1 if no field with this name is found.
     */
    static getFieldIndexForName(schema: BuilderSchemaAdapter, targetName: string): number {
        let index = 0;
        for (let field of schema.readFields()) {
            if (field.name === targetName) {
                return index;
            } else {
                index += 1;
            }
        }
        return -1;
    }


    /**
     * Retrieves the index of a section in the edited model based on the targetName.
     * @param schema Schema adapter of the edited model.
     * @param targetName The name of the section to search for.
     * @returns The index of the section, or -1 if no section with this name is found.
     */
    static getSectionIndexForName(schema: BuilderSchemaAdapter, targetName: string): number {
        let index = 0;
        for (let section of schema.readSections()) {
            if (section.name === targetName) {
                return index;
            } else {
                index += 1;
            }
        }
        return -1;
    }


    /**
     * Refreshes the list of field identifiers by clearing existing field names
     * and adding the current field names from the edited model.
     * @param schema Schema adapter of the edited model.
     * @param fieldIdentifierValidation Service for validating field identifiers.
     */
    static refreshFieldIdentifiers(schema: BuilderSchemaAdapter, fieldIdentifierValidation: FieldIdentifierValidationService): void {
        fieldIdentifierValidation.clearFieldNames();
        const fieldNames = schema.readFields().map(field => field.name);
        fieldIdentifierValidation.addFieldNames(fieldNames);
    }


    /**
     * Checks if a section is new.
     * @param section The section to check.
     * @param newSections Array of new sections.
     * @returns True if the section is new, false otherwise.
     */
    static isNewSection(section: BuilderSection, newSections: Array<BuilderSection>): boolean {
        return newSections.indexOf(section) > -1;
    }

    /**
     * Checks if a field is new.
     * @param field The field to check.
     * @param newFields Array of new fields.
     * @returns True if the field is new, false otherwise.
     */
    static isNewField(field: any, newFields: Array<any>): boolean {
        return newFields.some(newField => newField === field || newField?.name === field?.name);
    }

    /**
     * Opens the preview modal.
     * @param modalService The NgbModal service to open the modal.
     * @param sections The sections to pass to the modal.
     */
    static openPreview(modalService: NgbModal, sections: Array<any>): void {
        const previewModal = modalService.open(PreviewModalComponent, {
            size: 'lg',
            scrollable: true,
            windowClass: 'dg-modal-window',
            backdropClass: 'dg-modal-window-backdrop'
        });
        previewModal.componentInstance.sections = sections;
    }

    /**
     * Opens the diagnostic modal.
     * @param modalService The NgbModal service to open the modal.
     * @param sections The sections to pass to the modal.
     */
    static openDiagnostic(modalService: NgbModal, sections: Array<any>): void {
        const diagnosticModal = modalService.open(DiagnosticModalComponent, {
            size: 'lg',
            scrollable: true,
            windowClass: 'dg-modal-window',
            backdropClass: 'dg-modal-window-backdrop'
        });
        diagnosticModal.componentInstance.data = sections;
    }

    /**
     * Matches the input type to an icon.
     * @param value The value to match.
     * @returns The corresponding icon.
     */
    static matchedType(value: string): string {
        switch (value) {
            case 'textarea':
                return 'align-left';
            case 'password':
                return 'key';
            case 'number':
                return 'calculator';
            case 'checkbox':
                return 'check-square';
            case 'radio':
                return 'check-circle';
            case 'select':
                return 'list';
            case 'ref':
                return 'retweet';
            case 'location':
                return 'globe';
            case 'date':
                return 'calendar-alt';
            default:
                return 'font';
        }
    }


    /**
     * Matches a section type to its icon.
     *
     * Returns the shared constant, never a fresh array - see builder-icons.ts.
     *
     * @param value The section type.
     * @returns The icon prefix and name the palette entry uses.
     */
    static matchedSectionType(value: string): BuilderIcon {
        switch (value) {
            case 'multi-data-section':
                return MULTI_DATA_SECTION_ICON;
            case 'ref-section':
                return REF_SECTION_ICON;
            default:
                return SECTION_ICON;
        }
    }
}
