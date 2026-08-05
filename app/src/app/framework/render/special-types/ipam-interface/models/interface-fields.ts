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

export const IPAM_INTERFACE_SECTION_NAME = 'dg-ipam-interface';

export const IPAM_INTERFACE_FIELD_NAMES = {
    ACTIVE: 'dg-interface-active',
    TYPE: 'dg-interface-type',
    SUBNET: 'dg-interface-subnet',
    IP_ADDRESS: 'dg-interface-ip-address',
    HOST: 'dg-interface-host',
    DOMAIN: 'dg-interface-domain',
    MAC_ADDRESS: 'dg-interface-mac-address',
} as const;

/**
 * Every field name a dg-ipam-interface row must register on the modal form before backend
 * validation activates. Guards against partial / customised sections that share the IPAM
 * section name but don't carry the full IPAM interface schema.
 */
export const IPAM_INTERFACE_REQUIRED_FIELDS: ReadonlyArray<string> = [
    IPAM_INTERFACE_FIELD_NAMES.ACTIVE,
    IPAM_INTERFACE_FIELD_NAMES.TYPE,
    IPAM_INTERFACE_FIELD_NAMES.SUBNET,
    IPAM_INTERFACE_FIELD_NAMES.IP_ADDRESS,
    IPAM_INTERFACE_FIELD_NAMES.HOST,
    IPAM_INTERFACE_FIELD_NAMES.DOMAIN,
    IPAM_INTERFACE_FIELD_NAMES.MAC_ADDRESS,
];
