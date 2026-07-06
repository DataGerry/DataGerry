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

import { OUTLINE_HEADING_SELECTOR, OUTLINE_ID_ATTRIBUTE } from './docapi-outline-tree.util';
import { createOutlineId } from './docapi-outline-id.util';
import { resolveSectionRangeByHeadingId } from './docapi-outline-section-range.util';

const assignFreshIdsToClonedHeadings = (clonedNodes: Node[]): void => {
    clonedNodes.forEach((clonedNode) => {
        if (!(clonedNode instanceof HTMLElement)) {
            return;
        }

        const headingCandidates: HTMLElement[] = [];

        if (clonedNode.matches(OUTLINE_HEADING_SELECTOR)) {
            headingCandidates.push(clonedNode);
        }

        const nestedHeadings = Array.from(clonedNode.querySelectorAll(OUTLINE_HEADING_SELECTOR)) as HTMLElement[];
        headingCandidates.push(...nestedHeadings);

        headingCandidates.forEach((heading) => {
            heading.setAttribute(OUTLINE_ID_ATTRIBUTE, createOutlineId());
        });
    });
};

/**
 * Duplicate a section by stable outline heading ID.
 * Section range = heading block until next heading of same/higher level.
 */
export const duplicateSectionById = (htmlContent: string, headingId: string): string => {
    const sectionRange = resolveSectionRangeByHeadingId(htmlContent, headingId);
    if (!sectionRange) {
        return htmlContent;
    }

    const { body, bodyNodes, startIndex, endIndex } = sectionRange;

    const nodesToDuplicate = bodyNodes.slice(startIndex, endIndex + 1);
    if (nodesToDuplicate.length === 0) {
        return htmlContent;
    }

    const clonedNodes = nodesToDuplicate.map((node) => node.cloneNode(true));
    assignFreshIdsToClonedHeadings(clonedNodes);

    const insertionAnchor = bodyNodes[endIndex + 1] ?? null;
    if (insertionAnchor) {
        clonedNodes.forEach((node) => body.insertBefore(node, insertionAnchor));
    } else {
        clonedNodes.forEach((node) => body.appendChild(node));
    }

    return body.innerHTML;
};
