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
 * Reduces the applied ports section to the `uses_ports` flag and the `port_section_index` slot: the
 * builder shows it like any global template, but the type stores only those two - the ports
 * themselves live in their own collection. Both come from the model rather than from the section, so
 * an edit that never received the virtual template (missing IPAM licence) cannot silently switch
 * ports off or move them back to the top.
 */
export function withPortsFlagOnly(typeInstance: CmdbType): CmdbType {
    const usesPorts = typeInstance?.uses_ports === true;
    const sections = typeInstance?.render_meta?.sections ?? [];
    const portsIndex = sections.findIndex(section => isPortsTemplateName(section?.name));
    const payload = {
        ...typeInstance,
        uses_ports: usesPorts,
        port_section_index: usesPorts ? resolvePortSectionIndex(typeInstance, portsIndex) : 0
    } as CmdbType;

    if (portsIndex < 0) {
        return payload;
    }

    const portsSection = sections[portsIndex];

    const portFieldNames = new Set(
        (portsSection.fields ?? []).map(field => typeof field === 'string' ? field : field?.name)
    );

    payload.fields = (typeInstance?.fields ?? []).filter(field => !portFieldNames.has(field?.name));
    // A virtual template name is never a stored template id.
    payload.global_template_ids = (typeInstance?.global_template_ids ?? [])
        .filter(templateName => !isPortsTemplateName(templateName));
    // The meta step offers port fields too, so nothing may keep referencing them.
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


/**
 * Removing the ports section from the canvas list and putting it back at the same position are the
 * same index, so the canvas slot is stored as it stands. Without the section on the canvas the
 * stored slot is kept - an unlicensed edit has nothing to measure.
 */
function resolvePortSectionIndex(typeInstance: CmdbType, portsIndex: number): number {
    if (portsIndex >= 0) {
        return portsIndex;
    }

    const storedIndex = typeInstance?.port_section_index;

    return Number.isInteger(storedIndex) && storedIndex >= 0 ? storedIndex : 0;
}
