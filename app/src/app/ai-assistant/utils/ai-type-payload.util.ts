/*
* DATAGERRY - OpenSource Enterprise CMDB
* Copyright (C) 2025 becon GmbH
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

export interface PruneInput {
    schema: any;                       // full AI payload (result.data)
    sectionRows: Array<{               // minimal shape from the component
      meta: { name: string; fields?: string[] };
      form: { value: { includeSection: boolean; fieldChecks: boolean[] } };
    }>;
  }
  
  export function buildPrunedTypePayload({ schema, sectionRows }: PruneInput): any {
    const draft = JSON.parse(JSON.stringify(schema));
  
    const keptSections: any[] = [];
    const keptFieldNames = new Set<string>();
  
    for (const row of sectionRows) {
      const include = row.form.value.includeSection;
      if (!include) continue;
  
      const checks = row.form.value.fieldChecks;
      const originalNames = row.meta.fields ?? [];
      const filteredNames = originalNames.filter((_, i) => !!checks[i]);
  
      if (!filteredNames.length) continue;
  
      keptSections.push({ ...row.meta, fields: filteredNames });
      filteredNames.forEach(n => keptFieldNames.add(n));
    }
  
    // Replace sections
    draft.render_meta.sections = keptSections;
  
    // Keep only selected field definitions
    draft.fields = (draft.fields ?? []).filter((f: any) => keptFieldNames.has(f.name));
  
    // Trim summary fields
    if (draft.render_meta?.summary?.fields?.length) {
      draft.render_meta.summary.fields = draft.render_meta.summary.fields.filter((n: string) => keptFieldNames.has(n));
    }
  
    // Fix ci_explorer_label if it points to a removed field
    if (draft.ci_explorer_label && !keptFieldNames.has(draft.ci_explorer_label)) {
      draft.ci_explorer_label = null;
    }
  
    return draft;
  }
  