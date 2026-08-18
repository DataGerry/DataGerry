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
import { RackMountKind } from '../models/rack-overview.types';
/* ------------------------------------------------------------------------------------------------------------------ */

/** Accent used when a type carries no colour, or one that is not a plain hex value. */
const FALLBACK_ACCENT = '#64748b';

/** Icon used when a type carries no icon, or one that is not a Font Awesome class list. */
const FALLBACK_ICON = 'fas fa-microchip';

/** How each kind is named wherever a row is described. */
export const RACK_KIND_LABELS: Record<RackMountKind, string> = {
    [RackMountKind.MOUNT]: 'Mounted object',
    [RackMountKind.RESERVATION]: 'Reservation',
    [RackMountKind.BLOCKER]: 'Blocker'
};

/** An occupant has no type behind it, so its row is drawn with the icon of its kind. */
export const RACK_KIND_ICONS: Record<RackMountKind, string> = {
    [RackMountKind.MOUNT]: FALLBACK_ICON,
    [RackMountKind.RESERVATION]: 'fas fa-calendar-check',
    [RackMountKind.BLOCKER]: 'fas fa-ban'
};

const HEX_COLOR = /^#([\da-f]{3}|[\da-f]{6}|[\da-f]{8})$/i;

const ICON_TOKEN = /^fa[bdlrs]?$|^fa-[a-z\d-]+$/;

const MAX_ICON_TOKENS = 4;


/**
 * The type colour, accepted only as a plain hex value. Type metadata is author-supplied and ends up
 * in a style binding, so anything else is dropped rather than passed through.
 */
export function safeAccent(color: string | null | undefined): string {
    return color && HEX_COLOR.test(color.trim()) ? color.trim() : FALLBACK_ACCENT;
}


/** The same accent at low opacity, used to tint the row a device occupies. */
export function accentTint(color: string | null | undefined, alpha: number): string {
    const hex = safeAccent(color).slice(1);
    const full = hex.length === 3 ? hex.split('').map(char => char + char).join('') : hex;

    const red = parseInt(full.slice(0, 2), 16);
    const green = parseInt(full.slice(2, 4), 16);
    const blue = parseInt(full.slice(4, 6), 16);

    return `rgba(${red}, ${green}, ${blue}, ${alpha})`;
}


/**
 * The type icon, reduced to recognised Font Awesome tokens. Keeps an author-defined icon from
 * bringing along arbitrary classes when it lands in a class binding.
 */
export function safeIcon(icon: string | null | undefined): string {
    const tokens = (icon ?? '')
        .trim()
        .toLowerCase()
        .split(/\s+/)
        .filter(token => ICON_TOKEN.test(token))
        .slice(0, MAX_ICON_TOKENS);

    return tokens.some(token => token.startsWith('fa-')) ? tokens.join(' ') : FALLBACK_ICON;
}
