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

* You should have received a copy of the GNU Affero General Public License
* along with this program.  If not, see <https://www.gnu.org/licenses/>.
*/

import { Component, Input } from '@angular/core';

import { hexToRgb, normalizeHexColor } from '../../../core/utils/color-utils';


/**
 * Pill marking a type as one of the framework's special types.
 * Renders nothing for a regular type, so it can be dropped into a table cell unguarded.
 */
@Component({
    selector: 'cmdb-special-type-badge',
    templateUrl: './special-type-badge.component.html',
    styleUrls: ['./special-type-badge.component.scss'],
    standalone: false
})
export class SpecialTypeBadgeComponent {

    @Input() specialType: string | null;
    @Input() description: string = '';

    /** Accent of the leading dot, taken from the type's CI Explorer color. */
    public accentColor: string | null = null;
    public accentRing: string | null = null;


    /** Only a plain hex value may reach the style binding, the rest keeps the per-token accent. */
    @Input() set color(value: string | null) {
        const hex = normalizeHexColor(value);

        this.accentColor = hex;
        this.accentRing = hex ? `rgba(${hexToRgb(hex).join(', ')}, 0.18)` : null;
    }


    /** The backend stores the token in upper case; the list reads better with sentence casing. */
    public get displayToken(): string {
        const token = this.specialType ?? '';
        return token ? token.charAt(0).toUpperCase() + token.slice(1).toLowerCase() : '';
    }


    public get badgeClass(): string {
        // The token comes from the backend, so keep it to characters that can only form a class name
        const variant = (this.specialType ?? '').toLowerCase().replace(/[^a-z0-9_-]/g, '');
        return variant ? `special-type-badge special-type-badge--${variant}` : 'special-type-badge';
    }
}
