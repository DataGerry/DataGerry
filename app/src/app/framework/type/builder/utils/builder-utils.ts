import { CmdbType, CmdbTypeSection } from "src/app/framework/models/cmdb-type";
import { FieldIdentifierValidationService } from "../../services/field-identifier-validation.service";
import { NgbModal } from "@ng-bootstrap/ng-bootstrap";
import { DiagnosticModalComponent } from "../modals/diagnostic-modal/diagnostic-modal.component";
import { PreviewModalComponent } from "../modals/preview-modal/preview-modal.component";

export class BuilderUtils {

    /**
     * Retrieves the index of a field in the typeInstance based on the targetName.
     * @param typeInstance The current type instance containing fields.
     * @param targetName The name of the field to search for.
     * @returns The index of the field, or -1 if no field with this name is found.
     */
    static getFieldIndexForName(typeInstance: CmdbType, targetName: string): number {
        let index = 0;
        for (let field of typeInstance.fields) {
            if (field.name === targetName) {
                return index;
            } else {
                index += 1;
            }
        }
        return -1;
    }


    /**
     * Retrieves the index of a section in the typeInstance based on the targetName.
     * @param typeInstance The current type instance containing sections.
     * @param targetName The name of the section to search for.
     * @returns The index of the section, or -1 if no section with this name is found.
     */
    static getSectionIndexForName(typeInstance: CmdbType, targetName: string): number {
        let index = 0;
        for (let section of typeInstance.render_meta.sections) {
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
     * and adding the current field names from the type instance.
     * @param typeInstance The current type instance containing fields.
     * @param fieldIdentifierValidation Service for validating field identifiers.
     */
    static refreshFieldIdentifiers(typeInstance: CmdbType, fieldIdentifierValidation: FieldIdentifierValidationService): void {
        fieldIdentifierValidation.clearFieldNames();
        const fieldNames = typeInstance.fields.map(field => field.name);
        fieldIdentifierValidation.addFieldNames(fieldNames);
    }


    /**
     * Checks if a section is new.
     * @param section The section to check.
     * @param newSections Array of new sections.
     * @returns True if the section is new, false otherwise.
     */
    static isNewSection(section: CmdbTypeSection, newSections: Array<CmdbTypeSection>): boolean {
        return newSections.indexOf(section) > -1;
    }

    /**
     * Checks if a field is new.
     * @param field The field to check.
     * @param newFields Array of new fields.
     * @returns True if the field is new, false otherwise.
     */
    static isNewField(field: any, newFields: Array<CmdbTypeSection>): boolean {
        return newFields.some(newField => newField === field || newField?.name === field?.name);
    }

    /**
     * Opens the preview modal.
     * @param modalService The NgbModal service to open the modal.
     * @param sections The sections to pass to the modal.
     */
    static openPreview(modalService: NgbModal, sections: Array<any>): void {
        const previewModal = modalService.open(PreviewModalComponent, {
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
}
