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

* You should have received a copy of the GNU Affero General Public License
* along with this program. If not, see <https://www.gnu.org/licenses/>.
*/

import { CmdbType } from '../../../models/cmdb-type';
import { SpecialTypeSchema, SpecialTypeSchemaField, SpecialTypeSchemaSection } from '../../../models/special-type';

export interface SpecialTypeSchemaContent {
  fields: Array<SpecialTypeSchemaField>;
  sections: Array<SpecialTypeSchemaSection>;
  fieldNames: Set<string>;
  sectionNames: Set<string>;
  signature: string;
}

export interface SpecialTypeSchemaValidationResult {
  valid: boolean;
  message?: string;
}

export class SpecialTypeSchemaMapper {

  public static isValidSchemaShape(schema: SpecialTypeSchema | null | undefined): schema is SpecialTypeSchema {
    return !!schema
      && Array.isArray(schema.sections)
      && Array.isArray(schema.fields)
      && schema.sections.every(section => section?.name && Array.isArray(section?.fields))
      && schema.fields.every(field => field?.name);
  }


  public static validateSchema(schema: SpecialTypeSchema | null | undefined): SpecialTypeSchemaValidationResult {
    if (!this.isValidSchemaShape(schema)) {
      return {
        valid: false,
        message: 'Received an invalid special type schema from backend.'
      };
    }

    const fieldNames = new Set<string>(schema.fields.map(field => field.name));
    const unresolvedField = schema.sections
      .flatMap(section => section.fields.map(fieldName => ({ sectionName: section.name, fieldName })))
      .find(({ fieldName }) => !fieldNames.has(fieldName));

    if (unresolvedField) {
      return {
        valid: false,
        message: `Special type schema section "${unresolvedField.sectionName}" references unknown field "${unresolvedField.fieldName}".`
      };
    }

    return { valid: true };
  }


  public static buildContent(schema: SpecialTypeSchema): SpecialTypeSchemaContent {
    const fields = schema.fields.map(field => this.normalizeSchemaField(field));
    const sections = schema.sections.map(section => ({
      ...section,
      fields: [...section.fields]
    }));

    return {
      fields,
      sections,
      fieldNames: new Set<string>(fields.map(field => field.name)),
      sectionNames: new Set<string>(sections.map(section => section.name)),
      signature: this.createContentSignature(sections, fields)
    };
  }


  // Builds the canonical type content shape used to detect whether the selected schema is already applied.
  public static createTypeContentSignature(typeInstance: CmdbType): string {
    const sections = (typeInstance?.render_meta?.sections ?? []).map(section => ({
      ...section,
      fields: (section?.fields ?? [])
        .map(field => typeof field === 'string' ? field : field?.name)
        .filter(Boolean)
    }));
    const fields = (typeInstance?.fields ?? []).map(field => this.normalizeSchemaField(field));

    return this.createContentSignature(sections, fields);
  }


  private static normalizeSchemaField<T extends object>(field: T): T {
    const normalizedField = { ...field } as T & {
      options?: Array<Record<string, unknown>>;
    };

    if (Array.isArray(normalizedField.options)) {
      normalizedField.options = normalizedField.options.map(option => ({
        ...option,
        label: option.label ?? option.Label ?? option.name ?? ''
      }));
    }

    return normalizedField;
  }


  private static createContentSignature(
    sections: Array<SpecialTypeSchemaSection | Record<string, unknown>>,
    fields: Array<SpecialTypeSchemaField | Record<string, unknown>>
  ): string {
    return JSON.stringify(this.normalizeSignatureValue({ sections, fields }));
  }


  private static normalizeSignatureValue(value: unknown): unknown {
    if (Array.isArray(value)) {
      return value.map(item => this.normalizeSignatureValue(item));
    }

    if (!value || typeof value !== 'object') {
      return value;
    }

    return Object.keys(value)
      .sort()
      .reduce((normalizedValue: Record<string, unknown>, key: string) => {
        const propertyValue = (value as Record<string, unknown>)[key];

        if (propertyValue !== undefined) {
          normalizedValue[key] = this.normalizeSignatureValue(propertyValue);
        }

        return normalizedValue;
      }, {});
  }

}
