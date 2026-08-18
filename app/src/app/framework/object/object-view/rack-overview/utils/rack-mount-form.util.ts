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
import {
    RACK_SLOT_AREAS,
    RackArea,
    RackMountKind,
    RackMountPayload,
    RackMountRow,
    RackMountUpdatePayload,
    RackMountValidatePayload,
    kindOf
} from '../models/rack-overview.types';
/* ------------------------------------------------------------------------------------------------------------------ */

/**
 * The mount form's raw values, which is all these functions need: turning them into what the write
 * routes take is a pure translation, so it lives here rather than in the form's component.
 *
 * The numeric fields are read as number or string - a number input hands its value back as text.
 */
export interface RackMountFormValue {
    kind: RackMountKind;
    objectId: number | null;
    label: string | null;
    area: RackArea;
    startSlot: number | string | null;
    height: number | string | null;
    position: number | string | null;
    startDate: string | null;
    endDate: string | null;
    color: string | null;
}


/** Number inputs hand back strings, and the backend range-checks whatever it receives. */
export function toNumber(value: number | string | null): number | null {
    if (value == null || `${value}`.trim() === '') {
        return null;
    }

    return Number(value);
}


/** An emptied text input means "no value", which the backend spells as null. */
function toText(value: string | null): string | null {
    const text = (value ?? '').trim();

    return text === '' ? null : text;
}


/** The date input yields a plain day; the backend stores an instant, so it is sent as midnight UTC. */
function toIsoDate(value: string | null): string | null {
    return value ? `${value}T00:00:00+00:00` : null;
}


/**
 * Geometry of the candidate placement. The unused axis is sent as null so a move away from it clears
 * the stale value, and an omitted position lets the backend append to the area.
 */
function buildGeometry(value: RackMountFormValue): RackMountUpdatePayload {
    const { area, startSlot, height, position } = value;

    if (RACK_SLOT_AREAS.includes(area)) {
        return {
            area,
            start_slot: toNumber(startSlot),
            height: toNumber(height),
            position: null
        };
    }

    const geometry: RackMountUpdatePayload = {
        area,
        start_slot: null,
        height: area === RackArea.UNASSIGNED ? toNumber(height) : null
    };

    if (position != null && `${position}` !== '') {
        geometry.position = toNumber(position);
    }

    return geometry;
}


/**
 * Only the fields the chosen kind owns; the backend refuses the rest rather than ignoring them.
 * `existing` is the row being edited, whose object can no longer be swapped, or null when adding.
 */
function buildKindFields(value: RackMountFormValue, existing: RackMountRow | null): RackMountPayload {
    const { kind, objectId, label, startDate, endDate, color } = value;

    const payload: RackMountPayload = { kind, label: toText(label) };

    if (kind === RackMountKind.MOUNT) {
        payload.object_id = existing ? existing.object_id : objectId;
        return payload;
    }

    if (kind === RackMountKind.RESERVATION) {
        payload.start_date = toIsoDate(startDate);
        payload.end_date = toIsoDate(endDate);
        payload.color = toText(color);
    }

    return payload;
}


/** The dry run body. It carries the row's own id when editing, so it does not collide with itself. */
export function buildValidatePayload(
    value: RackMountFormValue,
    existing: RackMountRow | null
): RackMountValidatePayload {
    const payload: RackMountValidatePayload = {
        ...buildGeometry(value),
        ...buildKindFields(value, existing)
    };

    if (existing) {
        payload.mount_id = existing.mount_id;
    }

    return payload;
}


export function buildInsertPayload(value: RackMountFormValue): RackMountPayload {
    return {
        ...buildGeometry(value),
        ...buildKindFields(value, null)
    };
}


/**
 * The kind is immutable, so a PATCH carries the fields of the existing kind only. A null clears the
 * stored value, which is what an emptied input means.
 */
export function buildUpdatePayload(value: RackMountFormValue, existing: RackMountRow): RackMountUpdatePayload {
    const payload: RackMountUpdatePayload = {
        ...buildGeometry(value),
        label: toText(value.label)
    };

    if (kindOf(existing) === RackMountKind.RESERVATION) {
        payload.start_date = toIsoDate(value.startDate);
        payload.end_date = toIsoDate(value.endDate);
        payload.color = toText(value.color);
    }

    return payload;
}
