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
/* ------------------------------------------------------------------------------------------------------------------ */

/** The MDS section an interface row lives in. The only one the backend links today. */
export const IPAM_INTERFACE_SECTION_ID = 'dg-ipam-interface';

/** How a port relates to an interface. Fixed on the backend, so it is not an extendable option list. */
export enum InterfaceRelationType {
    PHYSICAL = 'PHYSICAL',
    BOND = 'BOND',
    VLAN = 'VLAN',
    VIRTUAL = 'VIRTUAL',
    OTHER = 'OTHER'
}


/** The labels of the fixed relation types, in the order the select offers them. */
export const INTERFACE_RELATION_TYPE_LABELS: ReadonlyArray<{ value: InterfaceRelationType; label: string }> = [
    { value: InterfaceRelationType.PHYSICAL, label: 'Physical' },
    { value: InterfaceRelationType.BOND, label: 'Bond' },
    { value: InterfaceRelationType.VLAN, label: 'VLAN' },
    { value: InterfaceRelationType.VIRTUAL, label: 'Virtual' },
    { value: InterfaceRelationType.OTHER, label: 'Other' }
];


/**
 * Which interface row a link points at.
 *
 * An interface is not an object of its own but one MDS row inside one, so it takes all three keys to
 * address it. `interface_multi_data_id` is the row id, which an ordinary object write can renumber -
 * that is what leaves a link dangling.
 */
export interface InterfaceRowRef {
    interface_object_id: number;
    interface_section_id: string;
    interface_multi_data_id: number;
}


/**
 * A link as `GET /ports/<port_id>/interface_links/` returns it.
 *
 * `interface_row` is the live row, read off the object on every request. It is absent - not null -
 * when the row it names no longer exists, which is the only way to tell a dangling link from a
 * healthy one.
 */
export interface PortInterfaceLink extends InterfaceRowRef {
    public_id: number;
    port_id: number;
    relation_type: InterfaceRelationType;
    author_id: number | null;
    creation_time: { $date: number } | null;
    last_edit_time: { $date: number } | null;
    interface_row?: MultiDataSectionSet;
}


/** Body of `POST /ports/<port_id>/interface_links/`. The port rides in the URL, not in the payload. */
export interface InterfaceLinkPayload {
    interface_object_id: number;
    interface_multi_data_id: number;
    relation_type: InterfaceRelationType;
}


/**
 * Body of `PUT /ports/interface_links/<public_id>`.
 *
 * Only the relation type can change; the row reference is the link's identity and is refused when it
 * names a different row, so it is sent back unchanged.
 */
export type InterfaceLinkUpdatePayload = InterfaceRowRef & { relation_type: InterfaceRelationType };


/** The subnet an assignable interface sits in, as the picker route names it. */
export interface AssignableInterfaceSubnet {
    public_id: number;
    name: string | null;
}


/** How the picker route names the object an interface row belongs to. */
export interface AssignableInterfaceObjectInfo {
    public_id: number;
    type_id: number;
    type_label: string | null;
    summary_line: string | null;
}


/**
 * One row of `GET /ports/<port_id>/assignable_interfaces/`.
 *
 * The route answers with the addresses already flattened, unlike a link's `interface_row`, which
 * carries the raw MDS fields. Rows already linked to the port are left out.
 */
export interface AssignableInterface extends InterfaceRowRef {
    subnet: AssignableInterfaceSubnet | null;
    object_info: AssignableInterfaceObjectInfo | null;
    active: boolean | null;
    ip: string | null;
    mac: string | null;
    hostname: string | null;
    domain: string | null;
    address_family: string | null;
}


/** One page of assignable interfaces. */
export interface AssignableInterfacePage {
    page: number;
    page_size: number;
    total: number;
    search: string;
    rows: AssignableInterface[];
}


/** Query of `GET /ports/<port_id>/assignable_interfaces/`. */
export interface AssignableInterfaceRequest {
    page: number;
    page_size: number;
    search?: string;
}


/**
 * An interface row the UI can render, whichever route it arrived on.
 *
 * The two routes describe the same row differently - flat keys from the picker, raw MDS fields from a
 * link - so both are normalised into this before anything displays them.
 */
export interface InterfaceRowView extends InterfaceRowRef {
    /** What the row is called: its host name, its address, or its row id. Never empty. */
    label: string;

    /** The addresses under the label, joined for the second line. Empty when the row has none. */
    details: string;

    ip: string | null;
    mac: string | null;
    hostname: string | null;
    domain: string | null;
    subnetName: string | null;
    interfaceType: string | null;
    active: boolean | null;

    /** The object holding the row, named the way the user recognises it. */
    objectLabel: string;
}


/** One row of the modal's list: the link, with its interface resolved unless it is dangling. */
export interface InterfaceLinkView {
    publicId: number;
    relationType: InterfaceRelationType;
    relationLabel: string;
    reference: InterfaceRowRef;

    /** Null while the row the link names no longer exists. */
    interface: InterfaceRowView | null;
}


/** What the ports table shows in its interface column. */
export interface PortInterfaceSummary {
    /** How the first resolvable interface reads. Null while every link of the port is dangling. */
    label: string | null;

    /** The address shown beside the label, left out when the label already is one. */
    address: string | null;

    /** The links beyond the shown one, named for the badge's tooltip. A dangling one reads as removed. */
    additionalLabels: string[];

    /** Links whose interface row is gone. */
    dangling: number;
}
