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
import { PortConnectionState } from './port-connection.types';
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
}


/** One table row: a port with its option ids resolved to the labels the user picked them by. */
export interface PortRow {
    publicId: number;
    name: string;
    side: PortSide;
    sideLabel: string;
    portNumber: number | null;
    status: string | null;
    portType: string | null;
    speed: string | null;
    description: string | null;
    connected: boolean;
    connectionState: PortConnectionState;

    /** What the connection cell reads: the cable in one line, the pairing, or "Free". */
    connectionLabel: string;

    /** The cable to edit or to cut; null while the port carries none. */
    cableConnectionId: number | null;

    /** The panel port on the other side of the internal pairing, which belongs to the same object. */
    pairedPortName: string | null;
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
