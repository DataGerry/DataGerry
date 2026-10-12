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

export enum SpecialType {
    SUPERNET = 'SUPERNET',
    SUBNET = 'SUBNET',
    VLAN = 'VLAN',
    RACK = 'RACK',
    CABLE = 'CABLE',
    PERSON = 'PERSON',
    PERSON_GROUP = 'PERSON_GROUP'
}


/**
 * The special types whose management needs the IPAM license - mirrors the backend's
 * SpecialType.get_license_gated_types. PERSON and PERSON_GROUP are a standard feature and stay out.
 */
export const LICENSE_GATED_SPECIAL_TYPES: ReadonlySet<string> = new Set<string>([
    SpecialType.SUPERNET,
    SpecialType.SUBNET,
    SpecialType.VLAN,
    SpecialType.RACK,
    SpecialType.CABLE
]);


/** Tolerates null and any unknown token, so a raw `special_type` marker can be passed straight in. */
export function isLicenseGatedSpecialType(value: string | null | undefined): boolean {
    return !!value && LICENSE_GATED_SPECIAL_TYPES.has(value);
}


export interface SpecialTypeSchemaSection {
    type: 'section';
    name: string;
    label: string;
    fields: Array<string>;
}


export interface SpecialTypeSchemaField {
    type: string;
    name: string;
    label: string;
}


export interface SpecialTypeSchema {
    special_type: SpecialType;
    sections: Array<SpecialTypeSchemaSection>;
    fields: Array<SpecialTypeSchemaField>;
}


export interface SpecialTypeOption {
    value: SpecialType;
    label: string;
    description: string;
}
