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
* along with this program.  If not, see <https://www.gnu.org/licenses/>.
*/
import { ImportTypeEntry } from '../../../models/import-type.models';
/* ------------------------------------------------------------------------------------------------------------------ */

/** Fallback icon for uploads that carry no (or an unusable) render meta icon. */
const DEFAULT_TYPE_ICON = 'fas fa-cube';

/** The icon comes from an uploaded file, so only plain class tokens are handed to the template. */
const ICON_CLASS_PATTERN = /^[a-z0-9 _-]+$/i;

/** One row of the upload preview list. `index` points back into the uploaded array. */
export interface TypePreviewRow {
    index: number;
    label: string;
    name: string;
    publicId: number | null;
    icon: string;
    fieldCount: number;
    sectionCount: number;
    searchTerm: string;
}


/** Flattens the uploaded entries into the little the preview list has to render. */
export function buildTypePreviewRows(types: ImportTypeEntry[] | null | undefined): TypePreviewRow[] {
    return (types ?? []).map((entry, index) => {
        const label = entry?.label || entry?.name || 'Unnamed type';
        const name = entry?.name || '—';

        return {
            index,
            label,
            name,
            publicId: typeof entry?.public_id === 'number' ? entry.public_id : null,
            icon: resolveIcon(entry?.render_meta?.icon),
            fieldCount: entry?.fields?.length ?? 0,
            sectionCount: entry?.render_meta?.sections?.length ?? 0,
            searchTerm: `${ label } ${ name }`.toLowerCase()
        };
    });
}


function resolveIcon(icon: string | undefined): string {
    return icon && ICON_CLASS_PATTERN.test(icon) ? icon : DEFAULT_TYPE_ICON;
}


export function filterTypePreviewRows(rows: TypePreviewRow[], search: string): TypePreviewRow[] {
    const term = search.trim().toLowerCase();

    if (!term) {
        return rows;
    }

    return rows.filter((row) => row.searchTerm.includes(term));
}
