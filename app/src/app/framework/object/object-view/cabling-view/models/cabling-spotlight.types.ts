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
/* ------------------------------------------------------------------------------------------------------------------ */

/** A selected cable, and the card and port it was picked by; both null when the cable itself was clicked. */
export interface CablingSelection {
    connectionId: number;
    objectId: number | null;
    portId: number | null;
}


/** While the spotlight is on: the ports it lifts above the shade, none until a port is picked. */
export interface CablingSpotlight {
    portIds: ReadonlySet<number>;
}


/** The picked cable and the cables back to the focal object, with every port they meet. */
export interface CablingTrace {
    connectionIds: ReadonlySet<number>;
    portIds: ReadonlySet<number>;
}
