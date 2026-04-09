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

import { OutlineNavItem, OutlineTreeBuildResult } from '../models/docapi-outline.model';
import { createOutlineId } from './docapi-outline-id.util';

export const OUTLINE_HEADING_SELECTOR = 'h1, h2, h3';
export const OUTLINE_ID_ATTRIBUTE = 'data-outline-id';

const SUPPORTED_HEADING_LEVELS = new Set([1, 2, 3]);

const getHeadingLevel = (heading: HTMLElement): number => Number(heading.tagName.slice(1));

const getHeadingText = (heading: HTMLElement): string => {
    const text = (heading.innerText || heading.textContent || '').trim();
    return text || 'Untitled heading';
};

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
    // IDs must persist on heading elements so outline actions can target the same section reliably.
    const headings = Array.from(body.querySelectorAll(OUTLINE_HEADING_SELECTOR)) as HTMLElement[];
    headings.forEach((heading) => ensureHeadingId(heading));
};

/**
 * Build a hierarchical outline tree from editor headings and keep stable heading IDs in-place.
 */
export const buildOutlineTree = (body: HTMLElement): OutlineTreeBuildResult => {
    ensureHeadingIds(body);

    const headings = Array.from(body.querySelectorAll(OUTLINE_HEADING_SELECTOR)) as HTMLElement[];
    const tree: OutlineNavItem[] = [];
    const stack: OutlineNavItem[] = [];
    const elementMap = new Map<string, HTMLElement>();

    headings.forEach((heading) => {
        const level = getHeadingLevel(heading);
        if (!SUPPORTED_HEADING_LEVELS.has(level)) {
            return;
        }

        const outlineItem: OutlineNavItem = {
            id: ensureHeadingId(heading),
            level,
            text: getHeadingText(heading),
            children: []
        };

        elementMap.set(outlineItem.id, heading);

        // Maintain the parent chain with a level stack (e.g. h3 belongs to nearest previous h1/h2).
        while (stack.length > 0 && stack[stack.length - 1].level >= outlineItem.level) {
            stack.pop();
        }

        if (stack.length === 0) {
            tree.push(outlineItem);
        } else {
            stack[stack.length - 1].children.push(outlineItem);
        }

        stack.push(outlineItem);
    });

    return { tree, elementMap };
};
