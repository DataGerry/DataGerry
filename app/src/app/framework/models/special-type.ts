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
    RACK = 'RACK'
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
