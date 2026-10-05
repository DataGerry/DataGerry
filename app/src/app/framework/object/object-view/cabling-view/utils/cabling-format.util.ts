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
import { hexToRgb, normalizeHexColor, safeCssColor } from 'src/app/core/utils/color-utils';

import { PortDeviceKind } from '../../ports-overview/models/port-bulk.types';
import { ResolvedCable } from '../../ports-overview/models/port-connection.types';
import { OverviewPort } from '../../ports-overview/models/ports-overview.types';
import {
    DEFAULT_CABLE_STROKE,
    DEFAULT_NODE_ICON,
    NEUTRAL_ACCENT,
    RESTRICTED_OBJECT_LABEL
} from '../constants/cabling.constants';
import { CablingEnd, CablingNode, CablingPortView, RestrictedCablingNode } from '../models/cabling.types';
/* ------------------------------------------------------------------------------------------------------------------ */

const ICON_PATTERN = /^[a-z0-9 -]+$/i;
const ICON_STYLE_PATTERN = /(^|\s)(fa|fas|far|fab|fa-solid|fa-regular|fa-brands)(\s|$)/;

/** Joins the parts that carry text; null when none does. */
function joinParts(parts: Array<string | null | undefined>, separator = ' · '): string | null {
    const filled = parts.map((part) => part?.trim()).filter((part): part is string => !!part);

    return filled.length ? filled.join(separator) : null;
}


export function isRestrictedNode(node: CablingNode | null | undefined): node is RestrictedCablingNode {
    return node?.restricted === true;
}


/** A restricted object never reads as a panel: its kind is not known. */
export function isPatchPanelNode(node: CablingNode | null | undefined): boolean {
    return !!node && !isRestrictedNode(node) && node.device_kind === PortDeviceKind.PATCH_PANEL;
}


/** The CI Explorer label field when the type names one, else the type and id. */
export function nodeTitle(node: CablingNode): string {
    if (isRestrictedNode(node)) {
        return RESTRICTED_OBJECT_LABEL;
    }

    const title = node.title == null ? '' : String(node.title).trim();

    return title || `${ node.type_info?.label || 'Object' } #${ node.object_id }`;
}


export function nodeSubtitle(node: CablingNode): string {
    return isRestrictedNode(node) ? 'No access to this object' : (node.type_info?.label ?? '');
}


/** A type icon is a class list; anything else falls back, and a bare `fa-x` gets its style prefix. */
export function nodeIcon(node: CablingNode): string {
    if (isRestrictedNode(node)) {
        return 'fas fa-lock';
    }

    const icon = node.type_info?.icon?.trim();

    if (!icon || !ICON_PATTERN.test(icon)) {
        return DEFAULT_NODE_ICON;
    }

    return ICON_STYLE_PATTERN.test(icon) ? icon : `fas ${ icon }`;
}


export function nodeAccent(node: CablingNode): string {
    return isRestrictedNode(node) ? NEUTRAL_ACCENT : (normalizeHexColor(node.type_info?.type_color) ?? NEUTRAL_ACCENT);
}


export function withAlpha(hex: string, alpha: number): string {
    const [red, green, blue] = hexToRgb(normalizeHexColor(hex) ?? NEUTRAL_ACCENT);

    return `rgba(${ red }, ${ green }, ${ blue }, ${ alpha })`;
}


/** A port counts as connected by its cable only; a panel face's internal pairing is drawn separately. */
export function hasCable(port: OverviewPort | null | undefined): boolean {
    return port?.cable_connection_id != null;
}


/** Names the far end the way the ports table does; a masked end never shows its id. */
export function farEndLabel(port: OverviewPort): string | null {
    const far = port.connected_object;

    if (far?.restricted) {
        return RESTRICTED_OBJECT_LABEL;
    }

    return joinParts([far?.label, port.connected_port?.name]);
}


export function portView(port: OverviewPort, drawnObjectIds: ReadonlySet<number>): CablingPortView {
    const cabled = hasCable(port);
    const farObjectId = port.connected_object?.object_id ?? null;
    const farEnd = cabled ? farEndLabel(port) : null;
    const name = port.name || '—';

    return {
        portId: port.port_id,
        name,
        side: port.side,
        cabled,
        connectionId: port.cable_connection_id ?? null,
        farEnd,
        meta: joinParts([port.port_type?.label, port.speed?.label, port.status?.label]) ?? joinParts([port.description]),
        expandable: cabled && farObjectId != null && !drawnObjectIds.has(farObjectId),
        expandLabel: `Show ${ farEnd ?? 'the far end' } of ${ name }`
    };
}


/** Name and length, as the mockup labels a cable; the type stands in when neither is known. */
export function cableLabel(cable: ResolvedCable | null | undefined): string {
    return joinParts([cable?.name, cable?.length]) ?? joinParts([cable?.type]) ?? 'Cable';
}


/**
 * The cable's own colour when a browser can paint it.
 *
 * The value is free text, so a word the browser does not know as a colour would otherwise paint
 * the line `none` and make it disappear.
 */
export function paintableCableColor(cable: ResolvedCable | null | undefined): string | null {
    const color = safeCssColor(cable?.color);

    if (!color) {
        return null;
    }

    return typeof CSS === 'undefined' || !CSS.supports || CSS.supports('color', color) ? color : null;
}


export function cableStroke(cable: ResolvedCable | null | undefined): string {
    return paintableCableColor(cable) ?? DEFAULT_CABLE_STROKE;
}


/** One sentence per cable, for the tooltip and the screen reader list. */
export function cableDescription(
    cable: ResolvedCable | null | undefined,
    from: CablingEnd,
    fromTitle: string,
    to: CablingEnd,
    toTitle: string
): string {
    const details = joinParts([cable?.type, cable?.color], ', ');
    const end = (title: string, portName: string | null) => joinParts([title, portName], ' ') ?? title;

    return `${ cableLabel(cable) }${ details ? ` (${ details })` : '' }: `
        + `${ end(fromTitle, from.port_name) } to ${ end(toTitle, to.port_name) }`;
}
