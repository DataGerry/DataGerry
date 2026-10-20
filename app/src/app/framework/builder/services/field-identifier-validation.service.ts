import { Injectable } from '@angular/core';

@Injectable({
    providedIn: 'root',
})
export class FieldIdentifierValidationService {
    private fieldNames: Set<string> = new Set();


    /**
     * Adds an array of field names to the service.
     * @param fieldNames - The array of field names to add.
     */
    addFieldNames(fieldNames: string[]): void {
        fieldNames.forEach(name => {
            if (name && name.trim() !== '') {
                this.fieldNames.add(name.trim());
            }
        });

    }

    /**
     * Checks if the provided field name is a duplicate.
     * @param newValue - The new value to check for duplication.
     * @returns true if the field name is a duplicate, false otherwise.
     */
    isDuplicate(newValue: string): boolean {
        if (!newValue || newValue.trim() === '') return false;

        const trimmedValue = newValue.trim();

        // Count the occurrences of the trimmedValue in the fieldNames set
        const duplicateCount = Array.from(this.fieldNames).filter(fieldName => fieldName === trimmedValue).length;

        return duplicateCount > 0;
    }


    /**
     * Clears all field names stored in the service (e.g., for form reset).
     */
    clearFieldNames(): void {
        this.fieldNames.clear();
    }
}
