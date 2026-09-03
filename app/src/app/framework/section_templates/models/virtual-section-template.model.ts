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
import { CmdbSectionTemplate } from 'src/app/framework/models/cmdb-section-template';
/* ------------------------------------------------------------------------------------------------------------------ */

/** Reserved name prefix of every virtual template. Refused by the create route. */
export const VIRTUAL_TEMPLATE_NAME_PREFIX = 'dg-virtual-tpl-';

/** A predefined global template the backend builds on request instead of storing. */
export interface VirtualSectionTemplate extends Omit<CmdbSectionTemplate, 'public_id'> {
    public_id?: never;
}

/** Either kind of template the overview lists. */
export type SectionTemplateListItem = CmdbSectionTemplate | VirtualSectionTemplate;

/** Keyed on the reserved prefix, not on a missing public_id. */
export function isVirtualSectionTemplate(template: SectionTemplateListItem): boolean {
    return isVirtualTemplateName(template?.name);
}

export function isVirtualTemplateName(name: string): boolean {
    return name?.startsWith(VIRTUAL_TEMPLATE_NAME_PREFIX) ?? false;
}

/** A type declares this template through `uses_ports`. */
const PORTS_VIRTUAL_TEMPLATE_NAME = `${VIRTUAL_TEMPLATE_NAME_PREFIX}ports`;

export function isPortsTemplateName(name: string): boolean {
    return name === PORTS_VIRTUAL_TEMPLATE_NAME;
}
