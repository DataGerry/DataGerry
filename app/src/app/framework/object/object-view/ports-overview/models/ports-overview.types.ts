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
import { PortOptionType } from 'src/app/framework/models/port-option-type';
import { PortInterfaceLink, PortInterfaceSummary } from './interface-link.types';
import { PortDeviceKind } from './port-bulk.types';
import { PortConnectionState, ResolvedCable } from './port-connection.types';
/* ------------------------------------------------------------------------------------------------------------------ */

/** The option lists the three select fields of a port draw their values from. */
export const PORT_OPTION_TYPES: readonly string[] = Object.values(PortOptionType);

/** ACL right guarding the port REST routes. */
export const PORT_VIEW_RIGHT = 'base.framework.port.view';

/** ACL rights the write routes are protected with. */
export const PORT_ADD_RIGHT = 'base.framework.port.add';
export const PORT_EDIT_RIGHT = 'base.framework.port.edit';
export const PORT_DELETE_RIGHT = 'base.framework.port.delete';

/** Which face of its object a port sits on. FRONT/REAR are a patch panel's two faces. */
export enum PortSide {
    SINGLE = 'single',
    FRONT = 'front',
    REAR = 'rear'
}


/**
 * A port as `GET /ports/object/<object_id>` returns it.
 *
 * The option fields hold a CmdbExtendableOption `public_id`, not a label. `connected` is derived on
 * read, so a backend without it omits the key.
 */
export interface CmdbPort {
    public_id: number;
    object_id: number;
    side: PortSide;
    name: string;
    port_number: number | null;
    status: number | null;
    port_type: number | null;
    speed: number | null;
    description: string | null;
    author_id: number | null;
    creation_time: { $date: number } | null;
    last_edit_time: { $date: number } | null;
    connected?: boolean;

    /** Embedded by the read route, with each link's `interface_row` resolved. Omitted by older backends. */
    interface_links?: PortInterfaceLink[];
}


/** An option field of the overview: the stored id and its resolved label. */
export interface PortOptionValue {
    id: number | null;
    label: string | null;
}


/** The far port of a cable. `name` and `side` are masked to null when the user may not read it. */
export interface OverviewConnectedPort {
    port_id: number;
    name: string | null;
    side: PortSide | null;
}


/** The object at the far end of a cable. `label` is null while `restricted`. */
export interface OverviewConnectedObject {
    object_id: number;
    label: string | null;
    restricted: boolean;
}


/** One port as `GET /ports/object/<object_id>/overview` returns it, labels and cable resolved. */
export interface OverviewPort {
    port_id: number;
    side: PortSide;
    port_number: number | null;
    name: string;
    description?: string | null;
    connected: boolean;
    cable: ResolvedCable | null;
    cable_connection_id: number | null;
    connected_port?: OverviewConnectedPort | null;
    connected_object: OverviewConnectedObject | null;
    interface_links: PortInterfaceLink[];
    status: PortOptionValue | null;
    port_type: PortOptionValue | null;
    speed: PortOptionValue | null;
}


/** A STANDARD device row: one port. */
export interface StandardOverviewRow {
    port: OverviewPort;
}


/** A PATCH_PANEL row: one pairing. An unpaired port leaves the other face null. */
export interface PatchPanelOverviewRow {
    front: OverviewPort | null;
    rear: OverviewPort | null;
    paired: boolean;
}


/** `device_kind` decides the row shape; an object without ports answers null with no rows. */
export type PortOverviewResponse =
    | { device_kind: null; rows: never[]; total: number }
    | { device_kind: PortDeviceKind.STANDARD; rows: StandardOverviewRow[]; total: number }
    | { device_kind: PortDeviceKind.PATCH_PANEL; rows: PatchPanelOverviewRow[]; total: number };


/** One port as the tables show it. */
export interface PortRow {
    publicId: number;
    name: string;
    side: PortSide;
    portNumber: number | null;
    status: string | null;
    portType: string | null;
    speed: string | null;
    description: string | null;
    connectionState: PortConnectionState;

    /** What the connection cell reads: the cable in one line, or "Free". */
    connectionLabel: string;

    /** The cable to edit or to cut; null while the port carries none. */
    cableConnectionId: number | null;

    /** The far end of the cable: its port and object, or a note that it is restricted. */
    farEndLabel: string | null;

    /** What the interfaces cell reads. */
    interfaces: PortInterfaceSummary;

    /** The interface label on its own, because the column sorts by a plain value. */
    interfaceLabel: string | null;
}


/** One patch panel pairing: the front and rear port side by side. */
export interface PatchPanelRow {
    /** Identifies the pairing; the front port's id, or the rear's when the front is missing. */
    key: number;
    portNumber: number | null;
    front: PortRow | null;
    rear: PortRow | null;
    paired: boolean;

    /** Flat sort keys, so the pairing sorts like any other row. */
    frontName: string | null;
    rearName: string | null;
    frontConnection: string | null;
    rearConnection: string | null;
}


/**
 * Body of `POST /ports/` and of `PUT /ports/<id>`, which take the whole port. The option fields
 * take an option's `public_id` or null, never a string.
 *
 *  `side` is left out on purpose: the route defaults a new port to SINGLE, and an update refuses
 * to move a port to another face - so neither write needs it.
 */
export interface PortPayload {
    object_id: number;
    name: string;
    port_number: number | null;
    status: number | null;
    port_type: number | null;
    speed: number | null;
    description: string | null;
}


/** The least a bulk dialog needs of a port: what to send, and what to name in the confirmation. */
export interface PortSelection {
    publicId: number;
    name: string;
}
