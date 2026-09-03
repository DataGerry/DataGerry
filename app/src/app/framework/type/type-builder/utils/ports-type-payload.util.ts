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
* along with this program. If not, see <https://www.gnu.org/licenses/>.
*/
import { CmdbType } from '../../../models/cmdb-type';
import { isPortsTemplateName } from 'src/app/framework/section_templates/models/virtual-section-template.model';
/* ------------------------------------------------------------------------------------------------------------------ */

/**
 * Reduces the applied ports section to the `uses_ports` flag: the builder shows it like any global
 * template, but the type stores only the flag - the ports themselves live in their own collection.
 * The flag comes from the model, not from the section, so an edit that never received the virtual
 * template (missing IPAM licence) cannot silently switch ports off.
 */
export function withPortsFlagOnly(typeInstance: CmdbType): CmdbType {
    const payload = { ...typeInstance, uses_ports: typeInstance?.uses_ports === true } as CmdbType;
    const sections = typeInstance?.render_meta?.sections ?? [];
    const portsSection = sections.find(section => isPortsTemplateName(section?.name));

    if (!portsSection) {
        return payload;
    }

    const portFieldNames = new Set(
        (portsSection.fields ?? []).map(field => typeof field === 'string' ? field : field?.name)
    );

    payload.fields = (typeInstance?.fields ?? []).filter(field => !portFieldNames.has(field?.name));
    // Types saved before the flag existed carry the reserved name here, which the backend calls a bug.
    payload.global_template_ids = (typeInstance?.global_template_ids ?? [])
        .filter(templateName => !isPortsTemplateName(templateName));
    // The meta step offers every model field, port fields included, so nothing may keep referencing them.
    payload.render_meta = {
        ...typeInstance.render_meta,
        sections: sections.filter(section => section !== portsSection),
        summary: {
            ...typeInstance.render_meta?.summary,
            fields: (typeInstance.render_meta?.summary?.fields ?? [])
                .filter(fieldName => !portFieldNames.has(fieldName))
        },
        externals: (typeInstance.render_meta?.externals ?? []).map(external => ({
            ...external,
            fields: (external?.fields ?? []).filter(fieldName => !portFieldNames.has(fieldName))
        }))
    };

    return payload;
}
