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

/**
 * Emphasis. Controls how much of the button is filled, not which colour it uses.
 */
export type ButtonVariant = 'solid' | 'soft' | 'outline' | 'ghost' | 'link';

/**
 * Meaning. Drives the fill, the label ink and the focus-ring hue.
 *
 * `success` is a status tone — a genuine approval or pass. Save, Add and Submit are
 * `brand`, not `success`.
 */
export type ButtonTone = 'brand' | 'neutral' | 'danger' | 'success' | 'warning' | 'info';

/**
 * Size step. Each one sets height, padding, type size, radius and icon size together.
 *
 * `xs` table row actions · `sm` toolbars and dense panels · `md` the default ·
 * `lg` modal footers and empty states.
 */
export type ButtonSize = 'xs' | 'sm' | 'md' | 'lg';

export type ButtonIconPosition = 'start' | 'end';

export type ButtonType = 'button' | 'submit' | 'reset';

/**
 * The variant/tone/size a `bootstrapClass` string resolves to.
 */
export interface ResolvedButtonStyle {
    variant: ButtonVariant;
    tone: ButtonTone;
    size?: ButtonSize;
    block?: boolean;
}
