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
import { CableOptionType } from 'src/app/framework/models/cable-option-type';
/* ------------------------------------------------------------------------------------------------------------------ */

/** The option lists a cable draws its values from. */
export const CABLE_OPTION_TYPES: readonly string[] = Object.values(CableOptionType);

/** ACL rights guarding the port-connection REST routes. */
export const CONNECTION_VIEW_RIGHT = 'base.framework.connection.view';
export const CONNECTION_ADD_RIGHT = 'base.framework.connection.add';
export const CONNECTION_EDIT_RIGHT = 'base.framework.connection.edit';
export const CONNECTION_DELETE_RIGHT = 'base.framework.connection.delete';

/** Frontend cap on the free-text cable fields; the backend stores them unbounded. */
export const CABLE_TEXT_MAX_LENGTH = 255;

/**
 * What a connection between two ports physically is.
 *
 * INTERNAL is never created from here: a patch panel's front-to-rear pairing is written by the bulk
 * creation, carries no cable information at all, and is refused an edit that names any.
 */
export enum ConnectionType {
    CABLE = 'CABLE',
    INTERNAL = 'INTERNAL'
}


/** Where the values of a cable come from, which is what the read routes report per connection. */
export enum CableSource {
    /** The connection owns them; `type_id` names a CABLE_TYPE option. */
    INLINE = 'inline',
    /** They are read off the linked CABLE SpecialType object; `type_id` is then null. */
    CI = 'ci'
}


/**
 * The cable of a connection, as the read routes resolve it.
 *
 * Both sources answer with the same keys, so a reader never has to know which one it got: `type` is
 * always a LABEL - resolved from the option for an inline cable, taken from the CI's field for a
 * linked one. `type_id` is what an edit form needs to preselect the option, and only an inline cable
 * has one: a CI stores the label rather than an option id.
 */
export interface ResolvedCable {
    source: CableSource;
    cable_ci_id: number | null;
    name: string | null;
    type: string | null;
    type_id: number | null;
    length: string | null;
    color: string | null;
    description: string | null;
}


/**
 * A cable CI that is free to be linked, as `GET /port_connections/cables/unassigned/` lists them.
 *
 * Asking for a connection returns its own cable as well, which is what makes the edit form able to
 * preselect it - a cable already in use is otherwise not part of the answer.
 */
export interface UnassignedCable {
    public_id: number;
    name: string | null;
    cable_type: string | null;
    active: boolean;
}


/**
 * What `GET /port_connections/cable_usage/<cable_public_id>` reports about a cable CI.
 *
 * `connection_id` and `endpoints` are filled in only while the cable is in use; `endpoints` names
 * the two ports of the connection holding it.
 */
export interface CableUsage {
    in_use: boolean;
    connection_id: number | null;
    endpoints: number[] | null;
}


/**
 * A connection as the `port_connections` routes return it.
 *
 * `endpoints` holds the two port ids sorted ascending - the link is undirected, so neither position
 * is the source. `cable` is absent on a patch panel's internal pairing, which has no cable at all.
 */
export interface CmdbPortConnection {
    public_id: number;
    endpoints: number[];
    connection_type: ConnectionType;
    cable?: ResolvedCable | null;
    author_id: number | null;
    creation_time: { $date: number } | null;
    last_edit_time: { $date: number } | null;
}


/**
 * The cable described on the connection itself.
 *
 * `cable_length` is text on purpose - '5 m', '2.5 m' are kept as the user wrote them. Both write
 * routes take the whole connection, so a key left out is unset rather than kept.
 */
export interface CableMetadataPayload {
    cable_name: string | null;
    cable_type: number | null;
    cable_length: string | null;
    cable_color: string | null;
    cable_description: string | null;
}


/**
 * The cable as an inventoried object: the reference alone.
 *
 * The five metadata keys are left out on purpose - the CI carries the same five fields, so sending
 * both would store the answer twice with no rule for which one wins. `cable_ci_id` is omitted
 * entirely rather than nulled whenever no CI is named: the index that gives one cable CI to one
 * connection is filtered on the key's presence, and a stored null would collide with every other
 * CI-less connection.
 */
export interface CableCiPayload {
    cable_ci_id: number;
}


/** The cable half of a write - described here, or referenced as a CI, never both. */
export type CableInfoPayload = CableMetadataPayload | CableCiPayload;


/** Body of `POST /port_connections/`. The endpoints and the type are immutable afterwards. */
export type PortConnectionPayload = {
    endpoints: number[];
    connection_type: ConnectionType;
} & CableInfoPayload;


/** How the user manages the cable of a connection: as plain metadata, or as an inventoried CI. */
export enum CableManagementMode {
    METADATA = 'METADATA',
    CABLE_CI = 'CABLE_CI'
}


/** What a port's connection cell reports. A panel port can be paired and cabled at the same time. */
export enum PortConnectionState {
    FREE = 'FREE',
    PAIRED = 'PAIRED',
    CABLED = 'CABLED'
}


/** The connections one port takes part in: at most one cable and, on a panel, one internal pairing. */
export interface PortConnectionInfo {
    state: PortConnectionState;
    cable: CmdbPortConnection | null;
    internal: CmdbPortConnection | null;
}


/** One end of a connection, named the way the user recognises it: device first, then port. */
export interface ConnectionEndpoint {
    portId: number;
    portName: string;
    sideLabel: string;
    objectId: number | null;
    objectLabel: string;
}
