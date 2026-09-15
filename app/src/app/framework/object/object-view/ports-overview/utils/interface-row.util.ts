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
import { MultiDataSectionSet } from 'src/app/framework/models/cmdb-object';
import { IPAM_INTERFACE_FIELD_NAMES } from 'src/app/framework/render/special-types/ipam-interface/models/interface-fields';
import {
    AssignableInterface,
    INTERFACE_RELATION_TYPE_LABELS,
    InterfaceLinkView,
    InterfaceRelationType,
    InterfaceRowView,
    PortInterfaceLink,
    PortInterfaceSummary
} from '../models/interface-link.types';
/* ------------------------------------------------------------------------------------------------------------------ */

/** Reads one field of an MDS row, which stores its fields as a list rather than as properties. */
function fieldValue(row: MultiDataSectionSet, name: string): string | null {
    const field = row?.data?.find((entry) => entry?.name === name);
    const value = field?.value;

    if (value === null || value === undefined || value === '') {
        return null;
    }

    return typeof value === 'string' ? value.trim() || null : String(value);
}


/** The interface's `active` flag, which the section stores as a checkbox value. */
function activeFlag(row: MultiDataSectionSet): boolean | null {
    const field = row?.data?.find((entry) => entry?.name === IPAM_INTERFACE_FIELD_NAMES.ACTIVE);

    return typeof field?.value === 'boolean' ? field.value : null;
}


/**
 * What an interface row is called.
 *
 * The section has no name field, so the label is derived: the host name if it has one, otherwise an
 * address, otherwise the row id. Every surface names a row through here, so the same row never reads
 * two different ways.
 */
export function interfaceRowLabel(parts: {
    hostname: string | null;
    domain: string | null;
    ip: string | null;
    mac: string | null;
    rowId: number;
}): string {
    if (parts.hostname) {
        return parts.domain ? `${ parts.hostname }.${ parts.domain }` : parts.hostname;
    }

    return parts.ip || parts.mac || `Row #${ parts.rowId }`;
}


/** The addresses shown under the label, skipping whatever the label already says. */
function interfaceRowDetails(view: Omit<InterfaceRowView, 'label' | 'details' | 'objectLabel'>, label: string): string {
    return [view.ip, view.mac, view.subnetName]
        .filter((part): part is string => !!part && part !== label)
        .join(' · ');
}


/** Names the object a row belongs to, falling back to its id when the read carried no summary. */
function objectLabelOf(info: { summary_line?: string | null; type_label?: string | null } | null, objectId: number): string {
    const label = (info?.summary_line ?? '').trim() || (info?.type_label ?? '').trim();

    return label || `Object #${ objectId }`;
}


/** The raw MDS row of a link, normalised into what the UI renders. */
export function interfaceRowFromLink(link: PortInterfaceLink): InterfaceRowView | null {
    const row = link?.interface_row;

    // Absent rather than null is how the backend reports a row that no longer exists.
    if (!row) {
        return null;
    }

    const base = {
        interface_object_id: link.interface_object_id,
        interface_section_id: link.interface_section_id,
        interface_multi_data_id: link.interface_multi_data_id,
        ip: fieldValue(row, IPAM_INTERFACE_FIELD_NAMES.IP_ADDRESS),
        mac: fieldValue(row, IPAM_INTERFACE_FIELD_NAMES.MAC_ADDRESS),
        hostname: fieldValue(row, IPAM_INTERFACE_FIELD_NAMES.HOST),
        domain: fieldValue(row, IPAM_INTERFACE_FIELD_NAMES.DOMAIN),
        subnetName: fieldValue(row, IPAM_INTERFACE_FIELD_NAMES.SUBNET),
        interfaceType: fieldValue(row, IPAM_INTERFACE_FIELD_NAMES.TYPE),
        active: activeFlag(row)
    };

    const label = interfaceRowLabel({ ...base, rowId: link.interface_multi_data_id });

    return {
        ...base,
        label,
        details: interfaceRowDetails(base, label),
        objectLabel: `Object #${ link.interface_object_id }`
    };
}


/** A picker row, which arrives with its addresses already flattened, normalised the same way. */
export function interfaceRowFromAssignable(row: AssignableInterface): InterfaceRowView {
    const base = {
        interface_object_id: row.interface_object_id,
        interface_section_id: row.interface_section_id,
        interface_multi_data_id: row.interface_multi_data_id,
        ip: row.ip ?? null,
        mac: row.mac ?? null,
        hostname: row.hostname ?? null,
        domain: row.domain ?? null,
        subnetName: row.subnet?.name ?? null,
        interfaceType: null,
        active: row.active ?? null
    };

    const label = interfaceRowLabel({ ...base, rowId: row.interface_multi_data_id });

    return {
        ...base,
        label,
        details: interfaceRowDetails(base, label),
        objectLabel: objectLabelOf(row.object_info, row.interface_object_id)
    };
}


/** The label of a relation type; an unknown value from a newer backend reads as itself. */
export function relationTypeLabel(relationType: InterfaceRelationType): string {
    return INTERFACE_RELATION_TYPE_LABELS.find((entry) => entry.value === relationType)?.label ?? String(relationType);
}


/** One link as the modal lists it. */
export function toInterfaceLinkView(link: PortInterfaceLink): InterfaceLinkView {
    return {
        publicId: link.public_id,
        relationType: link.relation_type,
        relationLabel: relationTypeLabel(link.relation_type),
        reference: {
            interface_object_id: link.interface_object_id,
            interface_section_id: link.interface_section_id,
            interface_multi_data_id: link.interface_multi_data_id
        },
        interface: interfaceRowFromLink(link)
    };
}


/**
 * What the table cell reads: the first resolvable interface, plus what else the port carries.
 *
 * A port whose every link is dangling keeps a null label, so the cell can say the interface is gone
 * instead of rendering an empty column nobody can explain.
 */
export function summarisePortInterfaces(links: readonly PortInterfaceLink[]): PortInterfaceSummary {
    const dangling = links.filter((link) => !link.interface_row).length;
    const first = links.map(interfaceRowFromLink).find((row): row is InterfaceRowView => !!row) ?? null;

    return {
        label: first?.label ?? null,
        // The label is already the address whenever the row has no host name.
        address: first && first.hostname ? first.ip : null,
        additional: Math.max(links.length - 1, 0),
        dangling
    };
}
