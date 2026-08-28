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
 * A section as the builder sees it, independent of the feature that owns it.
 *
 * Types, relations and section templates all describe a section the same way; the union of
 * their properties is small enough to state once here rather than have the kernel import
 * `CmdbTypeSection` and pretend a relation section is one.
 *
 * `fields` holds field **names** at rest and the resolved field objects while the builder is
 * open - the canvas hydrates it on load and the wizards flatten it again on save.
 */
export interface BuilderSection {
    type: string;
    name: string;
    label: string;
    fields?: Array<any>;
    bg_color?: string;

    /** multi-data-section only: fields hidden in the object view. */
    hidden_fields?: Array<string>;

    /** ref-section only: the type/section this section mirrors. */
    reference?: {
        type_id: number;
        section_name: string;
        selected_fields?: Array<string>;
    };
}
