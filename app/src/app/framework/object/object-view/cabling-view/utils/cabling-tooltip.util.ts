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
import { portSideLabel } from '../../ports-overview/utils/port-side.util';
import { CABLING_TOOLTIP } from '../constants/cabling.constants';
import { CablingCableTooltip, CablingTooltipEnd, CablingTooltipPlacement } from '../models/cabling-tooltip.types';
import { CablingSize } from '../models/cabling-viewport.types';
import { CablingEdge, CablingEnd, CablingNodeLayout, CablingPoint } from '../models/cabling.types';
import { cableStroke } from './cabling-format.util';
/* ------------------------------------------------------------------------------------------------------------------ */

const UNNAMED_CABLE = 'Unnamed cable';


/** The hovered cable's details; null when either end is not on the canvas. */
export function cableTooltip(
    edge: CablingEdge,
    layouts: ReadonlyMap<number, CablingNodeLayout>
): CablingCableTooltip | null {
    const fromNode = layouts.get(edge.from.object_id);
    const toNode = layouts.get(edge.to.object_id);

    if (!fromNode || !toNode) {
        return null;
    }

    const from = tooltipEnd(edge.from, fromNode);
    const to = tooltipEnd(edge.to, toNode);
    const name = filled(edge.cable?.name);
    const type = filled(edge.cable?.type);
    const details = [name ? type : null, filled(edge.cable?.length), filled(edge.cable?.color)].filter(Boolean);

    return {
        connectionId: edge.connection_id,
        title: name ?? type ?? UNNAMED_CABLE,
        stroke: cableStroke(edge.cable),
        details: details.length ? details.join(' · ') : null,
        description: filled(edge.cable?.description),
        ends: fromNode.x <= toNode.x ? [from, to] : [to, from]
    };
}


/** Centred over the spot, kept inside the frame; below it only when the room above runs out. */
export function placeCableTooltip(spot: CablingPoint, frame: CablingSize): CablingTooltipPlacement {
    const { width, maxHeight, gap, margin, arrowInset } = CABLING_TOOLTIP;
    const left = clamp(spot.x - width / 2, margin, frame.width - margin - width);
    const roomAbove = spot.y - gap - margin;

    return {
        x: spot.x,
        y: spot.y,
        offset: left - spot.x,
        arrow: clamp(spot.x - left, arrowInset, width - arrowInset),
        below: roomAbove < maxHeight && frame.height - spot.y > spot.y
    };
}

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

function tooltipEnd(end: CablingEnd, layout: CablingNodeLayout): CablingTooltipEnd {
    const port = filled(end.port_name);
    const side = portSideLabel(end.side) || null;

    return {
        title: layout.title,
        port,
        side: side && !port?.toLowerCase().startsWith(side.toLowerCase()) ? side : null,
        restricted: layout.restricted
    };
}


/** The low bound wins when the range is empty, so a frame narrower than the tooltip keeps its left edge. */
function clamp(value: number, min: number, max: number): number {
    return Math.max(min, Math.min(value, max));
}


function filled(value: string | null | undefined): string | null {
    return value?.trim() || null;
}
