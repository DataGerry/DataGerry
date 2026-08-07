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

export enum RackArea {
    FRONT = 'FRONT',
    BACK = 'BACK',
    FULL_DEPTH = 'FULL_DEPTH',
    LEFT = 'LEFT',
    RIGHT = 'RIGHT',
    UNASSIGNED = 'UNASSIGNED'
}

/** The two viewpoints a user can look at the rack from. */
export type RackViewSide = RackArea.FRONT | RackArea.BACK;

/** Areas anchored to slots. A FULL_DEPTH mount holds the same slots in both views. */
export const RACK_SLOT_AREAS: RackArea[] = [RackArea.FRONT, RackArea.BACK, RackArea.FULL_DEPTH];


export interface RackHeader {
    public_id: number;
    display_name: string;
    name: string | null;
    number: number | null;
    notes: string | null;
    height: number;
}


export interface RackMountRow {
    mount_id: number;
    object_id: number;
    area: RackArea;
    start_slot: number | null;
    height: number | null;
    position: number | null;
    summary_line: string | null;
    type_id: number | null;
    type_label: string | null;
    type_icon: string | null;
    type_color: string | null;
}


export type RackAreaBuckets = Record<RackArea, RackMountRow[]>;


export interface RackOverviewResponse {
    rack: RackHeader;
    areas: RackAreaBuckets;
    total_mounts: number;
}


export interface RackMountPayload {
    object_id: number;
    area?: RackArea;
    start_slot?: number | null;
    height?: number | null;
    position?: number | null;
}


/** Same body as a mount, plus the mount being moved so it is excluded from its own overlap check. */
export interface RackMountValidatePayload extends RackMountPayload {
    mount_id?: number;
}


/** PATCH applies only the keys it carries, so every field is optional. */
export interface RackMountUpdatePayload {
    area?: RackArea;
    start_slot?: number | null;
    height?: number | null;
    position?: number | null;
}


/** A stored mount as the raw list and lookup routes return it: no object resolution, no envelope. */
export interface RackMount {
    public_id: number;
    rack_id: number;
    object_id: number;
    area: RackArea;
    start_slot: number | null;
    height: number | null;
    position: number | null;
    author_id: number;
}


/**
 * An object this rack is allowed to take. The backend already drops the rack itself, other racks and
 * anything mounted elsewhere, so the picker shows exactly what can be mounted.
 */
export interface RackAssignableObject {
    public_id: number;
    summary_line: string;
    type_id: number;
    type_label: string;
    type_icon: string;
    type_color: string;
}


/** Informational answer to "which mounts would a shrink to this height displace?". */
export interface RackHeightConflictsResponse {
    height: number;
    conflicts: RackMountRow[];
    total: number;
}


export interface RackMountValidationError {
    message: string;
}


export interface RackMountValidationResponse {
    valid: boolean;
    errors: RackMountValidationError[];
}


/**
 * One rendered row of a rack side: either the top slot of a mount, spanning its height, or a single
 * free slot. Slots covered by a mount below its anchor are not emitted.
 */
export interface RackSlotRow {
    slot: number;
    span: number;
    mount: RackMountRow | null;
}


/** A rendered bucket of one of the areas that have no slot geometry. */
export interface RackAreaGroup {
    area: RackArea;
    title: string;
    mounts: RackMountRow[];
}
