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

const SUPPORTED_HEADING_LEVELS = new Set([1, 2, 3]);

const getHeadingLevel = (heading: HTMLElement): number => Number(heading.tagName.slice(1));

const ensureHeadingId = (heading: HTMLElement): string => {
    const existingId = heading.getAttribute(OUTLINE_ID_ATTRIBUTE);
    if (existingId) {
        return existingId;
    }

    const nextId = createOutlineId();
    heading.setAttribute(OUTLINE_ID_ATTRIBUTE, nextId);
    return nextId;
};

const ensureHeadingIds = (body: HTMLElement): void => {
    const headings = Array.from(body.querySelectorAll(OUTLINE_HEADING_SELECTOR)) as HTMLElement[];
    headings.forEach((heading) => ensureHeadingId(heading));
};

const resolveTopLevelBodyNode = (body: HTMLElement, node: Node): Node | null => {
    let currentNode: Node | null = node;

    while (currentNode && currentNode.parentNode && currentNode.parentNode !== body) {
        currentNode = currentNode.parentNode;
    }

    if (!currentNode || currentNode.parentNode !== body) {
        return null;
    }

    return currentNode;
};

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
    if (!htmlContent || !headingId) {
        return htmlContent;
    }

    const parser = new DOMParser();
    const parsedDocument = parser.parseFromString(htmlContent, 'text/html');
    const body = parsedDocument.body;

    ensureHeadingIds(body);

    const headings = Array.from(body.querySelectorAll(OUTLINE_HEADING_SELECTOR)) as HTMLElement[];
    const sourceHeadingIndex = headings.findIndex((heading) => heading.getAttribute(OUTLINE_ID_ATTRIBUTE) === headingId);
    if (sourceHeadingIndex < 0) {
        return htmlContent;
    }

    const sourceHeading = headings[sourceHeadingIndex];
    const sourceHeadingLevel = getHeadingLevel(sourceHeading);
    if (!SUPPORTED_HEADING_LEVELS.has(sourceHeadingLevel)) {
        return htmlContent;
    }

    const bodyNodes: Node[] = Array.from(body.childNodes);
    const sourceHeadingBodyNode = resolveTopLevelBodyNode(body, sourceHeading);
    if (!sourceHeadingBodyNode) {
        return htmlContent;
    }

    const startIndex = bodyNodes.indexOf(sourceHeadingBodyNode);
    if (startIndex < 0) {
        return htmlContent;
    }

    let endIndex = bodyNodes.length - 1;

    for (let index = sourceHeadingIndex + 1; index < headings.length; index += 1) {
        const candidateHeading = headings[index];
        const candidateHeadingLevel = getHeadingLevel(candidateHeading);

        if (candidateHeadingLevel > sourceHeadingLevel) {
            continue;
        }

        const candidateBodyNode = resolveTopLevelBodyNode(body, candidateHeading);
        const candidateIndex = candidateBodyNode ? bodyNodes.indexOf(candidateBodyNode) : -1;
        if (candidateIndex > startIndex) {
            endIndex = candidateIndex - 1;
            break;
        }
    }

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
