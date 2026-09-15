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
import { RenderResult } from 'src/app/framework/models/cmdb-render';
/* ------------------------------------------------------------------------------------------------------------------ */

/**
 * Names an object the way the user recognises it: its summary line, its type label, or its id.
 *
 * `objectId` is for a caller that knows which object it asked for and has to name it even when the
 * read answered with nothing.
 */
export function objectDisplayLabel(result: RenderResult | null | undefined, objectId?: number | null): string {
    const publicId = objectId ?? result?.object_information?.object_id ?? null;
    const suffix = publicId == null ? '' : `#${ publicId }`;
    const label = (result?.summary_line ?? '').trim() || result?.type_information?.type_label || '';

    if (!label) {
        return suffix ? `Object ${ suffix }` : 'Object';
    }

    // A summary line often already ends in the id; appending it again reads "#66 #66".
    return !suffix || label.endsWith(suffix) ? label : `${ label } ${ suffix }`;
}
