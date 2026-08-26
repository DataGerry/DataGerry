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
    RackArea,
    RackMountKind,
    RackMountRow,
    RackOccupantLegendEntry,
    RackOccupantLegendView,
    RackRowView,
    RackTypeLegendEntry,
    RackTypeLegendView,
    kindOf,
    toDayString
} from '../models/rack-overview.types';
import { gridRowOfPlacement, slotRangeText } from './rack-layout.util';
import { RACK_KIND_ICONS, RACK_KIND_LABELS, accentTint, safeAccent, safeIcon } from './rack-visual.util';
/* ------------------------------------------------------------------------------------------------------------------ */

/** Opacity of the row colour behind an icon chip or a side card. */
const TONE_TINT_ALPHA = 0.14;


/** The object page a row points at. Only a mount has one; an occupant stands for no object. */
export function objectRouteOf(objectId: number | null): string | null {
    return objectId == null ? null : `/framework/object/view/${objectId}`;
}


/** Every row of one overview, ready to draw. */
export function toRowViews(rows: RackMountRow[], rackHeight: number): RackRowView[] {
    return rows.map(row => toRowView(row, rackHeight));
}


export function toRowView(row: RackMountRow, rackHeight: number): RackRowView {
    const kind = kindOf(row);
    const isMount = kind === RackMountKind.MOUNT;
    const colorSource = colorSourceOf(row, kind);

    return {
        row,
        mountId: row.mount_id,
        objectId: row.object_id,
        objectRoute: isMount ? objectRouteOf(row.object_id) : null,
        area: row.area,
        startSlot: row.start_slot,
        height: row.height,
        position: row.position,
        isMount,
        isFullDepth: row.area === RackArea.FULL_DEPTH,
        label: labelOf(row, kind),
        kindTitle: RACK_KIND_LABELS[kind],
        typeName: isMount ? row.type_label || 'Object' : RACK_KIND_LABELS[kind],
        // The label of a mount is already the object, so it only adds something to a named occupant.
        secondaryLabel: isMount ? row.label?.trim() || null : null,
        period: periodOf(row),
        slotRange: slotRangeText(row.start_slot, row.height),
        gridRow: gridRowOfPlacement(row.start_slot, row.height, rackHeight),
        tone: safeAccent(colorSource),
        tint: accentTint(colorSource, TONE_TINT_ALPHA),
        icon: isMount ? safeIcon(row.type_icon) : RACK_KIND_ICONS[kind]
    };
}


/** The legend keys the drawing, so an entry reads its colour and icon the same way a row does. */
export function toTypeLegendView(entry: RackTypeLegendEntry): RackTypeLegendView {
    return {
        ...entry,
        tone: safeAccent(entry.type_color),
        tint: accentTint(entry.type_color, TONE_TINT_ALPHA),
        icon: safeIcon(entry.type_icon)
    };
}


export function toOccupantLegendView(entry: RackOccupantLegendEntry): RackOccupantLegendView {
    return { ...entry, title: RACK_KIND_LABELS[entry.kind], icon: RACK_KIND_ICONS[entry.kind] };
}

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

/** A mount is named by its object, an occupant by its own label and otherwise by its kind. */
function labelOf(row: RackMountRow, kind: RackMountKind): string {
    if (kind === RackMountKind.MOUNT) {
        return row.summary_line || `#${row.object_id}`;
    }

    return row.label?.trim() || RACK_KIND_LABELS[kind];
}


/** Where the row takes its colour from: its type for a mount, its own colour for a reservation. */
function colorSourceOf(row: RackMountRow, kind: RackMountKind): string | null {
    if (kind === RackMountKind.MOUNT) {
        return row.type_color;
    }

    return kind === RackMountKind.RESERVATION ? row.color : null;
}


/**
 * The booked period of a reservation, as plain days. Either end may be open, and a reservation without
 * any dates simply has no period to show.
 */
function periodOf(row: RackMountRow): string | null {
    const from = toDayString(row.start_date);
    const until = toDayString(row.end_date);

    if (from && until) {
        return `${from} to ${until}`;
    }

    if (from) {
        return `from ${from}`;
    }

    return until ? `until ${until}` : null;
}
