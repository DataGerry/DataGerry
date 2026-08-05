import { Injectable } from '@angular/core';
import { BehaviorSubject, Observable } from 'rxjs';

interface Section {
    newValue: string;
    index: number;
}

@Injectable({
    providedIn: 'root',
})
export class SectionIdentifierService {
    private sections: { [initialValue: string]: Section } = {};
    private isIdentifierValidSubject = new BehaviorSubject<boolean>(true);
    private activeIndexSubject = new BehaviorSubject<number | null>(null);

    constructor() { }


    /**
    * Resets the identifiers for all sections and updates the validity status.
    */
    public resetIdentifiers() {
        this.sections = {};
        this.setIsIdentifierValid(true);
        this.checkGlobalValidity();
    }


    /**
     * Rebuilds the identifier registry from the current builder sections.
     * This keeps generated or schema-locked sections reserved for duplicate checks.
     */
    public syncSections(sectionNames: string[]): void {
        this.sections = {};

        sectionNames.forEach((sectionName: string, index: number) => {
            this.sections[`${index}:${sectionName}`] = {
                newValue: sectionName,
                index
            };
        });

        this.checkGlobalValidity();
    }


    /**
     * Adds a new section at a specified index, adjusting subsequent sections' indices if necessary.
     * 
     * @param initialValue - The initial identifier of the section.
     * @param newValue - The new identifier of the section.
     * @param index - The position at which to insert the new section.
     * @returns Whether the addition was successful.
     */
    addSection(initialValue: string, newValue: string, index: number): boolean {
        if (this.sectionExists(newValue)) {
            this.checkGlobalValidity();
            return false;
        }

        // Adjust indices of sections that come after the new section
        for (const section of Object.values(this.sections)) {
            if (section.index >= index) {
                section.index += 1;
            }
        }

        this.sections[initialValue] = { newValue, index };
        this.checkGlobalValidity();
        return true;
    }


    /**
     * Gets the active index as an observable.
     * @returns Observable<number | null> - The active index or null.
     */
    getActiveIndex(): Observable<number> {
        return this.activeIndexSubject.asObservable();
    }


    /**
     * Sets the active index.
     * @param index - The index to be set as active.
     */
    setActiveIndex(index: number): void {
        this.activeIndexSubject.next(index);
    }


    /**
     * Retrieves the initial value of a section by its index.
     * @param index - The index to look up.
     * @returns string | null - The initial value corresponding to the given index, or null if not found.
     */
    private getInitialValueByIndex(index: number): string | null {
        const sectionEntry = Object.entries(this.sections).find(([_, section]) => section.index === index);
        return sectionEntry ? sectionEntry[0] : null;
    }


    /**
     * Updates an existing section's identifier.
     * 
     * @param newIndex - The index number of the section to update.
     * @param newValue - The new identifier to assign to the section.
     * @returns Whether the update was successful.
     */
    updateSection(newIndex: number, newValue: string): boolean {
        const initialValue = this.getInitialValueByIndex(newIndex);

        if (!initialValue) {
            this.checkGlobalValidity();
            return false;
        }

        if (!this.sections[initialValue]) {
            this.checkGlobalValidity();
            return false;
        }

        const oldIndex = this.sections[initialValue].index;
        delete this.sections[initialValue];

        if (this.sectionExists(newValue)) {
            this.sections[initialValue] = { newValue, index: oldIndex };
            this.checkGlobalValidity();
            return false;
        }

        this.sections[initialValue] = { newValue, index: oldIndex };
        this.checkGlobalValidity();
        return true;
    }


    /**
     * Checks if a section with a specified identifier exists.
     * 
     * @param newValue - The identifier to check for existence.
     * @returns Whether the section exists.
     */
    sectionExists(newValue: string): boolean {
        return Object.values(this.sections).some(section => section.newValue === newValue);
    }


    /**
     * Retrieves all sections managed by the service.
     * 
     * @returns An object containing all sections.
     */
    getSections(): { [initialValue: string]: Section } {
        return this.sections;
    }

    /**
     * Removes a section at a specified index and adjusts the indices of subsequent sections.
     * 
     * @param index - The index of the section to remove.
     */
    removeSection(index: number): void {
        const sectionEntries = Object.entries(this.sections);
        const sectionToRemove = sectionEntries.find(([_, section]) => section.index === index);

        if (!sectionToRemove) {
            return;
        }

        const [initialValueToRemove] = sectionToRemove;
        delete this.sections[initialValueToRemove];

        // Adjust indexes of remaining sections
        for (const section of Object.values(this.sections)) {
            if (section.index > index) {
                section.index -= 1;
            }
        }

        this.checkGlobalValidity();
    }


    /**
     * Updates the indices of sections after a drag-and-drop operation.
     * 
     * @param draggedIndex - The initial index of the dragged section.
     * @param newIndex - The new index where the section is dropped.
     */
    updateSectionIndexes(draggedIndex: number, newIndex: number): void {
        if (Math.abs(draggedIndex - newIndex) === 1 && draggedIndex < newIndex) {
            return;
        }

        if (draggedIndex === newIndex) {
            return;
        }

        if (draggedIndex < newIndex) {
            newIndex -= 1;
        }

        const sectionEntries = Object.entries(this.sections);
        const draggedSectionEntry = sectionEntries.find(([_, section]) => section.index === draggedIndex);

        if (!draggedSectionEntry) {
            return;
        }

        const [draggedInitialValue, draggedSection] = draggedSectionEntry;

        sectionEntries.forEach(([initialValue, section]) => {
            if (draggedIndex < newIndex) {
                if (section.index > draggedIndex && section.index <= newIndex) {
                    section.index -= 1;
                }
            } else if (draggedIndex > newIndex) {
                if (section.index < draggedIndex && section.index >= newIndex) {
                    section.index += 1;
                }
            }
        });

        draggedSection.index = newIndex;

        this.sections = sectionEntries.reduce((acc, [initialValue, section]) => {
            acc[initialValue] = section;
            return acc;
        }, {});

        this.checkGlobalValidity();
    }


    /**
    * Sets the validity status of the identifier.
    * 
    * @param isValid - The validity status to set.
    */
    private setIsIdentifierValid(isValid: boolean): void {
        this.isIdentifierValidSubject.next(isValid);
    }


    /**
     * Retrieves an observable that indicates the validity status of the identifier.
     * 
     * @returns An observable of the validity status.
     */
    getIsIdentifierValid(): Observable<boolean> {
        return this.isIdentifierValidSubject.asObservable();
    }

    /**
     * Checks the global validity of the section identifiers by ensuring all are unique.
     */
    private checkGlobalValidity(): void {
        const newValues = Object.values(this.sections).map(section => section.newValue);
        const uniqueValues = new Set(newValues);
        const isValid = newValues.length === uniqueValues.size;

        this.setIsIdentifierValid(isValid);
    }

    /**
     * Retrieves the index where a section is dropped.
     * 
     * @param index - The index where a section is dropped (optional).
     * @returns The dropped index.
     */
    getDroppedIndex(index?: number): number {
        return index;
    }
}
