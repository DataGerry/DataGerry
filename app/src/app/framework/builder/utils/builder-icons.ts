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

/** Font Awesome `[prefix, name]` tuple, the shape `<fa-icon [icon]>` expects. */
export type BuilderIcon = [string, string];

/**
 * The builder's section icons, as shared constants.
 *
 * They are constants rather than array literals returned from a helper on purpose. `fa-icon`
 * takes `icon` as a signal input, so a fresh array counts as a new value even when it holds the
 * same prefix and name: it invalidates the icon's rendered-HTML computed, schedules another change
 * detection run, and that run evaluates the binding again and hands over yet another fresh array.
 * A section card bound to a per-check literal therefore never lets the application go stable and
 * spins change detection until the tab stops responding.
 */
export const SECTION_ICON: BuilderIcon = ['fas', 'object-group'];
export const MULTI_DATA_SECTION_ICON: BuilderIcon = ['fas', 'list-ol'];
export const REF_SECTION_ICON: BuilderIcon = ['fas', 'layer-group'];

/** Header action of a section card: pencil when it may be edited, eye when it is read-only. */
export const SECTION_EDIT_ICON: BuilderIcon = ['far', 'edit'];
export const SECTION_READONLY_ICON: BuilderIcon = ['far', 'eye'];
