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
import { CINode } from 'src/app/framework/models/ci-explorer.model';
import { CmdbType } from 'src/app/framework/models/cmdb-type';

/** A field a node label can be built from. */
export interface LabelFieldOption {
    name: string;
    label: string;
    type: string;
    /** What the picker shows; carries the field name when two fields share a label. */
    display: string;
}

/**
 * The fields eligible as a CI Explorer label.
 *
 * A multi-data-section field holds one value per row rather than one per object, so it
 * cannot name a node.
 */
export function labelFieldOptions(type: CmdbType | null | undefined): LabelFieldOption[] {
    const eligible = new Set<string>(
        (type?.render_meta?.sections ?? [])
            .filter(section => section?.type !== 'multi-data-section')
            .flatMap(section => section?.fields ?? [])
            .map(field => (typeof field === 'string' ? field : field?.name))
            .filter(Boolean)
    );

    const options: LabelFieldOption[] = (type?.fields ?? [])
        .filter(field => eligible.has(field?.name))
        .map(field => {
            const label = field.label || field.name;
            return { name: field.name, label, type: field.type, display: label };
        });

    return disambiguate(options);
}


/** Two fields may carry the same label, so the ambiguous ones are shown with their name. */
function disambiguate(options: LabelFieldOption[]): LabelFieldOption[] {
    const seen = new Map<string, number>();
    options.forEach(option => seen.set(option.label, (seen.get(option.label) ?? 0) + 1));

    return options.map(option => (
        seen.get(option.label)! > 1 ? { ...option, display: `${option.label} (${option.name})` } : option
    ));
}

/** The value a node shows for a given label field; mirrors how the backend fills `title`. */
export function titleForLabelField(node: CINode, fieldName: string | null): string | null {
    if (!fieldName) {
        return null;
    }

    const field = node?.linked_object?.fields?.find(entry => entry?.name === fieldName);
    return field?.value == null ? '' : String(field.value);
}
