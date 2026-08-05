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
import { DocTemplatePageSection } from '../models/cmdb-doctemplate';

export const MIN_PAGE_SECTION_HEIGHT_PT = 20;
export const MAX_PAGE_SECTION_HEIGHT_PT = 80;
const DEFAULT_PAGE_SECTION_HEIGHT_PT = MIN_PAGE_SECTION_HEIGHT_PT;

export const DEFAULT_HEADER: DocTemplatePageSection = {
    activated: false,
    content: '',
    config: {
        height: DEFAULT_PAGE_SECTION_HEIGHT_PT
    }
};

export const DEFAULT_FOOTER: DocTemplatePageSection = {
    activated: false,
    content: '',
    config: {
        height: DEFAULT_PAGE_SECTION_HEIGHT_PT
    }
};

const normalizeSectionHeight = (rawValue: unknown): number => {
    const parsed = Number(rawValue);
    if (!Number.isFinite(parsed)) {
        return DEFAULT_PAGE_SECTION_HEIGHT_PT;
    }

    const value = Math.trunc(parsed);
    if (value < MIN_PAGE_SECTION_HEIGHT_PT) {
        return MIN_PAGE_SECTION_HEIGHT_PT;
    }

    if (value > MAX_PAGE_SECTION_HEIGHT_PT) {
        return MAX_PAGE_SECTION_HEIGHT_PT;
    }

    return value;
};

export const normalizePageSection = (
    rawSection: unknown,
    defaultSection: DocTemplatePageSection
): DocTemplatePageSection => {
    if (!rawSection || typeof rawSection !== 'object') {
        return {
            activated: defaultSection.activated,
            content: defaultSection.content,
            config: { ...defaultSection.config }
        };
    }

    const section = rawSection as Partial<DocTemplatePageSection>;
    const config = section.config && typeof section.config === 'object' ? section.config : {};

    return {
        activated: typeof section.activated === 'boolean' ? section.activated : defaultSection.activated,
        content: typeof section.content === 'string' ? section.content : defaultSection.content,
        config: {
            height: normalizeSectionHeight((config as Record<string, unknown>)['height'])
        }
    };
};

export const normalizeHeader = (rawHeader: unknown): DocTemplatePageSection =>
    normalizePageSection(rawHeader, DEFAULT_HEADER);

export const normalizeFooter = (rawFooter: unknown): DocTemplatePageSection =>
    normalizePageSection(rawFooter, DEFAULT_FOOTER);
