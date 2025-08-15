export interface SectionSelection {
  sectionName: string;            // section.name
  includeSection: boolean;        // section toggle
  includedFieldNames: string[];   // field names kept
}

export interface TypeSelectionPayload {
  sections: SectionSelection[];
}
