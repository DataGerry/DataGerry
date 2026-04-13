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
import {
    DocTemplateTableOfContents,
    DocTemplateTableOfContentsConfig,
    DocTemplateTocBaseStyle,
    DocTemplateTocFontStyle,
    DocTemplateTocFontWeight
} from '../models/cmdb-doctemplate';

export const DEFAULT_TABLE_OF_CONTENTS_CONFIG: DocTemplateTableOfContentsConfig = {
    pdftoc: {
        'line-height': 1.4
    },
    level0: {
        'font-size': 12,
        'margin-top': 10,
        'margin-bottom': 4,
        'padding-bottom': 2,
        color: '#000000',
        'font-style': 'normal',
        'font-weight': 'bold'
    },
    level1: {
        'font-size': 10,
        'margin-left': 12,
        'margin-top': 3,
        'margin-bottom': 2,
        'padding-bottom': 1,
        color: '#222222',
        'font-style': 'normal'
    },
    level2: {
        'font-size': 9,
        'margin-left': 24,
        'margin-top': 2,
        'margin-bottom': 2,
        'padding-bottom': 1,
        color: '#444444',
        'font-style': 'italic'
    },
    level3: {
        'font-size': 9,
        'margin-left': 36,
        'margin-top': 2,
        'margin-bottom': 2,
        'padding-bottom': 1,
        color: '#555555',
        'font-style': 'normal'
    },
    level4: {
        'font-size': 8,
        'margin-left': 48,
        'margin-top': 2,
        'margin-bottom': 2,
        'padding-bottom': 1,
        color: '#666666',
        'font-style': 'normal'
    },
    level5: {
        'font-size': 8,
        'margin-left': 60,
        'margin-top': 2,
        'margin-bottom': 2,
        'padding-bottom': 1,
        color: '#777777',
        'font-style': 'italic'
    }
};

export const DEFAULT_TABLE_OF_CONTENTS: DocTemplateTableOfContents = {
    activated: false,
    config: DEFAULT_TABLE_OF_CONTENTS_CONFIG
};

const HEX_COLOR_PATTERN = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i;

const parseNumber = (value: unknown, fallback: number, min: number, max: number): number => {
    const parsed = Number(value);
    if (!Number.isFinite(parsed)) {
        return fallback;
    }

    return Math.min(Math.max(parsed, min), max);
};

const normalizeColor = (value: unknown, fallback: string): string => {
    if (typeof value !== 'string') {
        return fallback;
    }

    const color = value.trim();
    if (!HEX_COLOR_PATTERN.test(color)) {
        return fallback;
    }

    if (color.length === 4) {
        return `#${color[1]}${color[1]}${color[2]}${color[2]}${color[3]}${color[3]}`;
    }

    return color;
};

const normalizeFontStyle = (value: unknown, fallback: DocTemplateTocFontStyle): DocTemplateTocFontStyle => {
    return value === 'italic' || value === 'normal' ? value : fallback;
};

const normalizeFontWeight = (value: unknown, fallback: DocTemplateTocFontWeight): DocTemplateTocFontWeight => {
    return value === 'bold' || value === 'normal' ? value : fallback;
};

const normalizeLevelStyle = (value: unknown, fallback: DocTemplateTocBaseStyle): DocTemplateTocBaseStyle => {
    const style = value && typeof value === 'object' ? value as Record<string, unknown> : {};

    return {
        'font-size': parseNumber(style['font-size'], fallback['font-size'] ?? 10, 1, 64),
        'margin-left': parseNumber(style['margin-left'], fallback['margin-left'] ?? 0, 0, 240),
        'margin-top': parseNumber(style['margin-top'], fallback['margin-top'] ?? 0, 0, 120),
        'margin-bottom': parseNumber(style['margin-bottom'], fallback['margin-bottom'] ?? 0, 0, 120),
        'padding-bottom': parseNumber(style['padding-bottom'], fallback['padding-bottom'] ?? 0, 0, 120),
        color: normalizeColor(style['color'], fallback.color ?? '#000000'),
        'font-style': normalizeFontStyle(style['font-style'], fallback['font-style'] ?? 'normal'),
        'font-weight': normalizeFontWeight(style['font-weight'], fallback['font-weight'] ?? 'normal')
    };
};

export const normalizeTableOfContentsConfig = (rawConfig: unknown): DocTemplateTableOfContentsConfig => {
    const config = rawConfig && typeof rawConfig === 'object' ? rawConfig as Record<string, unknown> : {};
    const defaults = DEFAULT_TABLE_OF_CONTENTS_CONFIG;

    const rawPdftoc = config['pdftoc'] && typeof config['pdftoc'] === 'object'
        ? config['pdftoc'] as Record<string, unknown>
        : {};

    return {
        pdftoc: {
            'line-height': parseNumber(rawPdftoc['line-height'], defaults.pdftoc['line-height'], 0.6, 4)
        },
        level0: normalizeLevelStyle(config['level0'], defaults.level0),
        level1: normalizeLevelStyle(config['level1'], defaults.level1),
        level2: normalizeLevelStyle(config['level2'], defaults.level2),
        level3: normalizeLevelStyle(config['level3'], defaults.level3),
        level4: normalizeLevelStyle(config['level4'], defaults.level4),
        level5: normalizeLevelStyle(config['level5'], defaults.level5)
    };
};

export const normalizeTableOfContents = (rawTableOfContents: unknown): DocTemplateTableOfContents => {
    if (!rawTableOfContents || typeof rawTableOfContents !== 'object') {
        return {
            activated: DEFAULT_TABLE_OF_CONTENTS.activated,
            config: normalizeTableOfContentsConfig(DEFAULT_TABLE_OF_CONTENTS.config)
        };
    }

    const tableOfContents = rawTableOfContents as Partial<DocTemplateTableOfContents>;
    const hasActivatedFlag = Object.prototype.hasOwnProperty.call(tableOfContents, 'activated');

    return {
        activated: typeof tableOfContents.activated === 'boolean'
            ? tableOfContents.activated
            : (hasActivatedFlag ? DEFAULT_TABLE_OF_CONTENTS.activated : false),
        config: normalizeTableOfContentsConfig(tableOfContents.config)
    };
};
