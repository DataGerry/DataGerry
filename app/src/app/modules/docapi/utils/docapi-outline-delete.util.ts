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

import { resolveSectionRangeByHeadingId } from './docapi-outline-section-range.util';

/**
 * Delete a section by stable outline heading ID.
 * Section range = heading block until next heading of same/higher level.
 */
export const deleteSectionById = (htmlContent: string, headingId: string): string => {
    const sectionRange = resolveSectionRangeByHeadingId(htmlContent, headingId);
    if (!sectionRange) {
        return htmlContent;
    }

    const { body, bodyNodes, startIndex, endIndex } = sectionRange;

    const nodesToDelete = bodyNodes.slice(startIndex, endIndex + 1);
    if (nodesToDelete.length === 0) {
        return htmlContent;
    }

    nodesToDelete.forEach((node) => {
        body.removeChild(node);
    });

    return body.innerHTML;
};
