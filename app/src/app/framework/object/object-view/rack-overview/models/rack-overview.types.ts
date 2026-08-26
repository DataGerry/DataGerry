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

/**
 * Every rack write route is guarded by the EDIT right - no rack route uses `rack.add` or `rack.delete` -
 * so the frontend gates each rack action with the same one.
 */
export const RACK_EDIT_RIGHT = 'base.framework.rack.edit';

/** Guards every rack read route, and with it the rack tab of the object view. */
export const RACK_VIEW_RIGHT = 'base.framework.rack.view';

/**
 * The notes are a field of the rack object rather than rack data of their own, so they are written
 * through the object PATCH route - and are gated by the object right, not the rack one.
 */
export const OBJECT_EDIT_RIGHT = 'base.framework.object.edit';

/** Name of the notes field of the RACK special type. */
export const RACK_NOTES_FIELD = 'dg-rack-notes';


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


/**
 * What holds the slots. A MOUNT is an object in the rack; a RESERVATION books the space for later and
 * has to be released before anything can be mounted there; a BLOCKER simply takes the space out of use.
 * The last two carry no object and are called occupants.
 */
export enum RackMountKind {
    MOUNT = 'MOUNT',
    RESERVATION = 'RESERVATION',
    BLOCKER = 'BLOCKER'
}

export const RACK_OCCUPANT_KINDS: RackMountKind[] = [RackMountKind.RESERVATION, RackMountKind.BLOCKER];

/** The side areas hold objects only, so an occupant may take any other area. */
export const RACK_OCCUPANT_FORBIDDEN_AREAS: RackArea[] = [RackArea.LEFT, RackArea.RIGHT];


export type RackApiDate = string | number | { $date: string | number } | null;


/** The day of an API date, as `YYYY-MM-DD`, which is what a date input reads and writes. */
export function toDayString(value: RackApiDate): string | null {
    if (value === null || value === undefined || value === '') {
        return null;
    }

    if (typeof value === 'string') {
        return value.slice(0, 10);
    }

    const parsed = new Date(typeof value === 'number' ? value : value.$date);

    return Number.isNaN(parsed.getTime()) ? null : parsed.toISOString().slice(0, 10);
}


/** A row without a kind predates the occupants and is an object mount. */
export function kindOf(row: { kind?: RackMountKind | null }): RackMountKind {
    return row?.kind ?? RackMountKind.MOUNT;
}

export function isOccupant(row: { kind?: RackMountKind | null }): boolean {
    return RACK_OCCUPANT_KINDS.includes(kindOf(row));
}


export interface RackHeader {
    public_id: number;
    display_name: string;
    name: string | null;
    number: number | null;
    notes: string | null;
    height: number;
}


/**
 * One row shape for all three kinds: a mount carries the object and its type metadata and leaves the
 * reservation fields null, an occupant does the opposite. The label is the only field all three share.
 */
export interface RackMountRow {
    mount_id: number;
    kind: RackMountKind;
    object_id: number | null;
    label: string | null;
    area: RackArea;
    start_slot: number | null;
    height: number | null;
    position: number | null;
    start_date: RackApiDate;
    end_date: RackApiDate;
    color: string | null;
    summary_line: string | null;
    type_id: number | null;
    type_label: string | null;
    type_icon: string | null;
    type_color: string | null;
}


export type RackAreaBuckets = Record<RackArea, RackMountRow[]>;


/** How much of the rack the occupants of one kind hold. Absent kinds simply have no entry. */
export interface RackOccupantLegendEntry {
    kind: RackMountKind;
    count: number;
    slots: number;
}


/** One object type present in the rack, with the colour and icon its rows are drawn with. */
export interface RackTypeLegendEntry {
    type_id: number;
    type_label: string;
    type_icon: string | null;
    type_color: string | null;
    count: number;
}


export interface RackOverviewResponse {
    rack: RackHeader;
    areas: RackAreaBuckets;
    total_mounts: number;
    types_legend: RackTypeLegendEntry[];
    occupants_legend: RackOccupantLegendEntry[];
}


/**
 * The body that creates a row. Which keys are allowed depends on the kind: a MOUNT needs an object and
 * refuses the reservation fields, a RESERVATION refuses the object, and a BLOCKER refuses both.
 */
export interface RackMountPayload {
    kind?: RackMountKind;
    object_id?: number | null;
    label?: string | null;
    area?: RackArea;
    start_slot?: number | null;
    height?: number | null;
    position?: number | null;
    start_date?: string | null;
    end_date?: string | null;
    color?: string | null;
}


/** Same body as a new row, plus the row being moved so it is excluded from its own overlap check. */
export interface RackMountValidatePayload extends RackMountPayload {
    mount_id?: number;
}


/**
 * PATCH applies only the keys it carries, so every field is optional and null clears a value. The kind
 * is immutable and therefore absent.
 */
export interface RackMountUpdatePayload {
    area?: RackArea;
    start_slot?: number | null;
    height?: number | null;
    position?: number | null;
    label?: string | null;
    start_date?: string | null;
    end_date?: string | null;
    color?: string | null;
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
 * An object this rack is allowed to take. The backend drops the rack itself and other racks, but an
 * object mounted in another rack is still offered and carries the rack it currently sits in -
 * mounting it here moves it. Request `only_unmounted` to get the free objects only.
 */
export interface RackAssignableObject {
    public_id: number;
    summary_line: string;
    type_id: number;
    type_label: string;
    type_icon: string;
    type_color: string;
    assigned_rack_id: number | null;
    assigned_rack_name: string | null;
}


/**
 * An assignable object plus the label the picker renders for it. The dropdown binds a plain property
 * path, so the rack hint is composed once per row instead of in the template.
 */
export interface RackAssignableOption extends RackAssignableObject {
    option_label: string;
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
 * Which elevations are drawn. `split` shows both faces beside one shared U ruler, the other two show a
 * single face with a ruler on each of its posts.
 */
export type RackViewMode = 'split' | 'front' | 'rear';


/** How full one face of the rack is. The largest gap is what says whether the free U are usable. */
export interface RackCapacity {
    total: number;
    used: number;
    free: number;
    percent: number;
    largestGap: number;
}


export interface RackRowView {
    /** The row exactly as the backend reports it, which is what the write routes are given. */
    row: RackMountRow;
    mountId: number;
    objectId: number | null;
    /** The object page this row links to, or null for a row that stands for no object. */
    objectRoute: string | null;
    area: RackArea;
    startSlot: number | null;
    height: number | null;
    position: number | null;
    isMount: boolean;
    isFullDepth: boolean;
    label: string;
    kindTitle: string;
    typeName: string;
    secondaryLabel: string | null;
    period: string | null;
    slotRange: string;
    gridRow: string;
    tone: string;
    tint: string;
    icon: string;
}


/** One U of the rack: the grid row it occupies, and whether the ruler marks it. */
export interface RackSlotView {
    slot: number;
    gridRow: string;
    isMajor: boolean;
}


/** A legend type with the colour and icon its rows are drawn with. */
export interface RackTypeLegendView extends RackTypeLegendEntry {
    tone: string;
    tint: string;
    icon: string;
}


/** A legend occupant kind, named and iconed the way its rows are. */
export interface RackOccupantLegendView extends RackOccupantLegendEntry {
    title: string;
    icon: string;
}


/**
 * One drawn elevation: the rows holding slots on that face, the slots still open, and how full it is.
 * A FULL_DEPTH row belongs to both faces and is therefore part of both.
 */
export interface RackFace {
    side: RackViewSide;
    title: string;
    units: RackRowView[];
    freeSlots: RackSlotView[];
    capacity: RackCapacity;
}


/** A rendered bucket of one of the areas that have no slot geometry. */
export interface RackAreaGroup {
    area: RackArea;
    title: string;
    mounts: RackRowView[];
}
