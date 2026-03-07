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
export interface PageMargins {
    top: number;
    bottom: number;
    left: number;
    right: number;
}

export const DEFAULT_PAGE_MARGINS: Readonly<PageMargins> = {
    top: 20,
    bottom: 20,
    left: 20,
    right: 20
};

const PAGE_MARGINS_START_MARKER = '/* DATAGERRY_PAGE_MARGINS_START */';
const PAGE_MARGINS_END_MARKER = '/* DATAGERRY_PAGE_MARGINS_END */';

export function parseMarginValue(value: unknown): number | null {
    const parsed = Number(value);
    if (!Number.isFinite(parsed) || parsed < 0) {
        return null;
    }
    return parsed;
}

export function parsePageMarginsFromStyle(styleValue?: string, defaults: PageMargins = DEFAULT_PAGE_MARGINS): PageMargins {
    if (!styleValue) {
        return { ...defaults };
    }

    const top = extractMarginProperty(styleValue, 'margin-top');
    const bottom = extractMarginProperty(styleValue, 'margin-bottom');
    const left = extractMarginProperty(styleValue, 'margin-left');
    const right = extractMarginProperty(styleValue, 'margin-right');

    return {
        top: top ?? defaults.top,
        bottom: bottom ?? defaults.bottom,
        left: left ?? defaults.left,
        right: right ?? defaults.right
    };
}

export function upsertPageMarginsStyleBlock(existingStyle: string, margins: PageMargins): string {
    const marginBlock = createPageMarginsBlock(margins);
    const markerRegex = new RegExp(
        `${escapeRegex(PAGE_MARGINS_START_MARKER)}[\\s\\S]*?${escapeRegex(PAGE_MARGINS_END_MARKER)}`,
        'm'
    );

    if (markerRegex.test(existingStyle)) {
        return existingStyle.replace(markerRegex, marginBlock);
    }

    if (!existingStyle.trim()) {
        return marginBlock;
    }

    return `${marginBlock}\n\n${existingStyle}`;
}

function createPageMarginsBlock(margins: PageMargins): string {
    return [
        PAGE_MARGINS_START_MARKER,
        '@page {',
        `  margin-top: ${margins.top}mm;`,
        `  margin-bottom: ${margins.bottom}mm;`,
        `  margin-left: ${margins.left}mm;`,
        `  margin-right: ${margins.right}mm;`,
        '}',
        PAGE_MARGINS_END_MARKER
    ].join('\n');
}

function extractMarginProperty(styleValue: string, propertyName: string): number | null {
    const regex = new RegExp(`${propertyName}\\s*:\\s*([0-9]*\\.?[0-9]+)\\s*mm`, 'i');
    const match = styleValue.match(regex);
    if (!match?.[1]) {
        return null;
    }
    const parsed = Number(match[1]);
    return Number.isFinite(parsed) ? parsed : null;
}

function escapeRegex(value: string): string {
    return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}
